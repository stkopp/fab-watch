from urllib.parse import quote, unquote, urlencode, urljoin, urlsplit
from uuid import UUID

from transport import fetch, now

FAB = "https://www.fab.com"


def seller_name(value):
    raw = value.strip()
    parts = urlsplit(raw if "://" in raw else "https://" + raw)
    segments = parts.path.strip("/").split("/")
    if (parts.scheme != "https" or parts.netloc.lower() not in {"fab.com", "www.fab.com"}
            or len(segments) not in (2, 3) or segments[0] != "sellers"
            or (len(segments) == 3 and segments[2] not in {"about", "listings"})):
        raise ValueError("Enter a Fab seller link such as https://www.fab.com/sellers/Your%20Name.")
    name = unquote(segments[1]).strip()
    if not name or len(name) > 150 or any(c in name for c in "/\\?#") or any(ord(c) < 32 for c in name):
        raise ValueError("The seller name in this link is invalid.")
    return name


def resolve_seller(value):
    name = seller_name(value)
    profile = fetch(f"{FAB}/i/sellers/name/{quote(name, safe='')}")
    actual, seller_id = profile.get("sellerName"), profile.get("sellerId")
    if profile.get("isSeller") is not True or not actual or not seller_id:
        raise ValueError("Fab did not return an active seller profile for this link.")
    return {"id": str(seller_id), "name": actual, "url": f"{FAB}/sellers/{quote(actual, safe='')}"}


def catalog_url(name):
    return f"{FAB}/i/listings/search?{urlencode({'seller': name, 'sort_by': 'listingTypeWeight'})}"


def catalog(name):
    url, items, visited = catalog_url(name), {}, set()
    while url:
        if url in visited or len(visited) > 100:
            raise ValueError('Catalog pagination did not advance')
        visited.add(url)
        if urlsplit(url).netloc != "www.fab.com" or urlsplit(url).path != "/i/listings/search":
            raise ValueError("Unexpected catalog pagination URL")
        page = fetch(url)
        if not isinstance(page.get('results'), list) or 'next' not in page:
            raise ValueError('Catalog schema changed')
        for p in page['results']:
            uid, title = p['uid'], p['title']
            if str(UUID(uid)) != uid or not isinstance(title, str) or uid in items:
                raise ValueError("Invalid or repeated catalog item")
            kind = 'bundles' if p['listingType'] == 'bundle' else 'listings'
            items[uid] = {'uid': uid, 'title': title, 'kind': kind,
                          'url': f'https://www.fab.com/{kind}/{uid}'}
        url = urljoin(url, page['next']) if page['next'] else None
    return items


def reviews(uid):
    start, total, result = 0, None, {}
    for _ in range(1000):
        page = fetch(f'https://www.fab.com/i/store/listings/{uid}/reviews?start={start}')
        rows, paging = page['elements'], page['paging']
        if (not isinstance(rows, list) or paging['start'] != start
                or type(paging['total']) is not int or paging['total'] < 0
                or type(paging['count']) is not int):
            raise ValueError('Review pagination/schema mismatch')
        if total is None:
            total = paging['total']
        if total != paging['total']:
            raise ValueError('Reviews changed during pagination; retry next run')
        for r in rows:
            if r['targetId'] != uid or not isinstance(r['uid'], str) or not r['uid'] or r['uid'] in result:
                raise ValueError('Wrong or repeated review')
            result[r['uid']] = {k: r.get(k) for k in
                ('uid', 'authorDisplayName', 'authorEpicId', 'targetOwner', 'title', 'content', 'rating',
                 'createdAt', 'lastModifiedAt')}
        if len(result) == total:
            return result
        if not rows or paging['count'] <= 0 or len(result) > total:
            raise ValueError('Incomplete review list')
        start += paging['count']
    raise ValueError('Review pagination limit reached')


def review_changes(old, current, product):
    if old is None:
        return []
    changes = []
    for uid, review in current.items():
        previous = old.get(uid)
        kind = 'new_review' if previous is None else 'edited_review'
        if previous is None or any(previous.get(k) != review.get(k) for k in ('title', 'content', 'rating')):
            changes.append({'kind': kind, 'product': product['title'], 'url': product['url'],
                            'review_id': uid, 'review': review})
    return changes


def forum_snapshot(thread_id, old, backfill=False):
    url = f'https://forums.unrealengine.com/t/{thread_id}.json'
    topic = fetch(url)
    if topic['id'] != thread_id:
        raise ValueError('Wrong forum topic')
    stream = topic['post_stream']['stream']
    if (not isinstance(stream, list) or any(type(i) is not int or i < 1 for i in stream)
            or len(stream) != len(set(stream)) or len(stream) != topic['posts_count']):
        raise ValueError('Incomplete forum post ID list')
    previous = set() if backfill else set(old['seen_ids']) if old else set(stream)
    added = set(stream) - previous
    posts = {p['id']: p for p in topic['post_stream']['posts'] if p['id'] in added}
    missing = sorted(added - posts.keys())
    for offset in range(0, len(missing), 20):
        query = urlencode([('post_ids[]', p) for p in missing[offset:offset + 20]])
        page = fetch(f'https://forums.unrealengine.com/t/{thread_id}/posts.json?{query}')
        for p in page['post_stream']['posts']:
            if p['id'] in added:
                posts[p['id']] = p
    if set(posts) != added:
        raise ValueError('Could not retrieve every new forum post; checkpoint unchanged')
    first = next((p for p in topic['post_stream']['posts'] if p.get('post_number') == 1), {})
    snapshot = {'thread_id': thread_id, 'url': f'https://forums.unrealengine.com/t/{thread_id}',
                'seen_ids': sorted(previous | set(stream)), 'current_ids': stream,
                'posts_count': topic['posts_count'], 'highest_post_number': topic['highest_post_number'],
                'last_posted_at': topic.get('last_posted_at'), 'checked_at': now(),
                'owner_id': first.get('user_id') or (old or {}).get('owner_id'),
                'owner_username': first.get('username') or (old or {}).get('owner_username'),
                'history_loaded': True}
    if old:
        snapshot['seen_ids'] = sorted(set(snapshot['seen_ids']) | set(old['seen_ids']))
    return snapshot, sorted(posts.values(), key=lambda p: p['post_number'])
