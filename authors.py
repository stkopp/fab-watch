def own_message(event):
    if event["kind"] == "new_comment":
        user_id = event.get("author_id")
        owner_id = event.get("owner_id")
        if owner_id is not None and user_id is not None:
            return str(user_id) == str(owner_id)
        if event.get("owner_username"):
            return str(event.get("author") or "").casefold() == event["owner_username"].casefold()
    if event["kind"] in ("new_review", "edited_review"):
        review = event.get("review") or {}
        author, owner = review.get("authorEpicId"), review.get("targetOwner")
        if author and owner:
            return author == owner
    return False
