import logging
from contextlib import contextmanager
from datetime import datetime

import sources
import transport
from authors import own_message
from storage import encode, identity
from transport import SourceError, now

FAB = "https://www.fab.com"


@contextmanager
def source_attempt(errors, stage, url, last_success=None):
    transport.fetch.last_shape = None
    try:
        yield
    except SourceError as exc:
        errors.append({"stage": stage, "url": url, "category": exc.category,
                       "message": str(exc), "status": exc.status, "shape": exc.shape,
                       "last_success": last_success})
    except (KeyError, TypeError, ValueError, AttributeError, IndexError) as exc:
        # Only parsing failures raised inside a source attempt are classified here.
        message = str(exc) if isinstance(exc, (KeyError, ValueError)) else type(exc).__name__
        category = "incomplete" if message.startswith(("Incomplete", "Reviews changed")) else "schema"
        errors.append({"stage": stage, "url": url, "category": category,
                       "message": message[:240], "status": 200, "shape": transport.fetch.last_shape,
                       "last_success": last_success})
    if errors and errors[-1]["url"] == url and errors[-1]["stage"] == stage:
        logging.info("Source %s %s: %s", stage, url, errors[-1]["category"])


def historical(stamp, start):
    if not start:
        return False
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")) <= datetime.fromisoformat(start)
    except (TypeError, ValueError, AttributeError):
        return True


@transport.connection_scope()
def collect(db, seller):
    errors = []
    transport.cooldown = db.meta("cooldown", {})
    active = None
    with source_attempt(errors, "catalog", sources.catalog_url(seller["name"]), db.meta("catalog_checked_at")):
        active = sources.catalog(seller["name"])
    if active is not None:
        with db.db:
            db.db.executemany("INSERT OR REPLACE INTO products VALUES (?,?)",
                              [(uid, encode(p)) for uid, p in active.items()])
            db.set_meta("active_product_ids", list(active))
            db.set_meta("catalog_checked_at", now())
    products = db.products()
    active_ids = set(db.meta("active_product_ids", list(products)))
    review_checks = forum_checks = 0
    for uid, product in products.items():
        if uid not in active_ids:
            continue
        old_detail = db.source(uid, "detail") or {}
        detail = None
        url = f'{FAB}/i/{product["kind"]}/{uid}'
        with source_attempt(errors, "listing", url, old_detail.get("detail_checked_at")):
            data = sources.fetch(url)
            if data["uid"] != uid or data["commentThreadStatus"] not in (None, "active"):
                raise ValueError("Unexpected listing ID or discussion status")
            if not isinstance(data["ratings"], dict) or type(data["ratings"]["total"]) is not int:
                raise ValueError("Missing total rating count")
            detail = {"ratings": data["ratings"], "comment_status": data["commentThreadStatus"],
                      "detail_checked_at": now()}
        if detail is not None:
            with db.db:
                db.set_source(uid, "detail", detail)
        previous = db.source(uid, "reviews") or {}
        latest = None
        with source_attempt(errors, "reviews", f"{FAB}/i/store/listings/{uid}/reviews",
                            previous.get("checked_at")):
            latest = sources.reviews(uid)
        if latest is not None:
            save_reviews(db, product, previous, latest, detail)
            review_checks += 1

        link = db.source(uid, "forum_link")
        if detail and detail["comment_status"] == "active":
            discovered = None
            with source_attempt(errors, "discussion_link", f"{url}/comment-thread",
                                (link or {}).get("checked_at")):
                thread_id = sources.fetch(f"{FAB}/i/listings/{uid}/comment-thread")["threadId"]
                if type(thread_id) is not int or thread_id <= 0:
                    raise ValueError("Invalid forum topic ID")
                discovered = {"id": thread_id, "checked_at": now()}
            if discovered:
                link = discovered
                with db.db:
                    db.set_source(uid, "forum_link", link)
        if link and check_forum(db, product, link["id"], errors):
            forum_checks += 1

    with db.db:
        db.set_meta("cooldown", transport.cooldown)
        db.set_meta("last_run_at", now())
        db.set_meta("last_errors", errors)
        if not errors:
            db.set_meta("last_success_at", now())
    status = "connection_unavailable" if transport.connection_problem(errors) else "partial_failure" if errors else "ok"
    return {"status": status, "products": len(active_ids),
            "review_sources": review_checks, "forums": forum_checks, "errors": errors}


def save_reviews(db, product, previous, latest, detail):
    uid = product["uid"]
    known = previous.get("known", {})
    changes = sources.review_changes(known, latest, product)
    old_ratings = previous.get("ratings")
    ratings = detail["ratings"] if detail else old_ratings
    written_delta = sum(e["kind"] == "new_review" for e in changes)
    with db.db:
        for event in changes:
            review = event["review"]
            if own_message(event) or historical(review.get("createdAt"), db.meta("tracking_started_at")):
                event["silent"] = True
            if event["kind"] == "new_review" and review.get("createdAt"):
                event["detected_at"] = review["createdAt"] if event.get("silent") else now()
            if event["kind"] == "edited_review":
                event["silent"] = True
                key = identity("review_edit", uid, event["review_id"], review["lastModifiedAt"], review["content"])
            else:
                key = identity("review", uid, event["review_id"])
            db.event(key, event)
        if old_ratings and ratings:
            delta = ratings["total"] - old_ratings["total"] - written_delta
            if delta > 0:
                db.event(identity("rating", uid, previous["checked_at"], ratings["total"]), {
                    "kind": "ratings_changed", "product": product["title"], "url": product["url"],
                    "delta": delta, "before": old_ratings, "after": ratings})
        db.set_source(uid, "reviews", {"known": {**known, **latest}, "current": list(latest),
                                       "checked_at": now(), "ratings": ratings})


def check_forum(db, product, thread_id, errors):
    uid = product["uid"]
    stage = f"forum:{thread_id}"
    previous = db.source(uid, stage)
    result = None
    with source_attempt(errors, "forum", f"https://forums.unrealengine.com/t/{thread_id}.json",
                        (previous or {}).get("checked_at")):
        snapshot, posts = sources.forum_snapshot(thread_id, previous or {"seen_ids": []},
                                                backfill=not (previous or {}).get("history_loaded"))
        old_ids = set((previous or {}).get("seen_ids", []))
        # Validate all new posts before committing any of them.
        events = [{
            "kind": "new_comment", "product": product["title"],
            "url": f'{snapshot["url"]}/{p["post_number"]}', "post_id": p["id"],
            "post_number": p["post_number"], "author": p["username"],
            "author_id": p.get("user_id"), "author_name": p.get("name"),
            "owner_id": snapshot["owner_id"], "owner_username": snapshot["owner_username"],
            "silent": p["id"] in old_ids or historical(p["created_at"], db.meta("tracking_started_at")),
            "created_at": p["created_at"], "content_html": p["cooked"],
        } for p in posts if p["post_number"] != 1]
        result = snapshot, events
    if result is None:
        return False
    snapshot, events = result
    batch = []
    for event in events:
        if own_message(event):
            event["silent"] = True
        if event.get("silent"):
            event["detected_at"] = event["created_at"]
        batch.append((identity("post", thread_id, event["post_id"]), event))
    db.commit_source_batch(uid, stage, snapshot, batch)
    return True
