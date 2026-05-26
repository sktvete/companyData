"""Server-backed favorites session (demo users). ChatGPT OAuth is browser-local only."""

from __future__ import annotations



from typing import Any



from flask import session



import moonstocks_store as ms_store

from pathlib import Path



# Playground personas for nav sign-in (favorites only; ChatGPT OAuth stays separate).

DEMO_USERS: dict[str, tuple[str, str]] = {

    "sindre": ("demo:sindre", "Sindre"),

    "ask": ("demo:ask", "Ask"),

    "test": ("demo:test", "Test"),

    "alexander": ("demo:alexander", "Alexander"),

}





def _favorites_payload(project_root: Path, user_id: str) -> dict[str, Any]:

    user = ms_store.get_user(project_root, user_id)

    favs = ms_store.list_favorites(project_root, user_id)

    return {

        "userSignedIn": True,

        "userId": user_id,

        "displayName": (user or {}).get("display_name") or (user_id[:8] + "…"),

        "favoritesCount": len(favs),

    }





def auth_payload(project_root: Path) -> dict[str, Any]:

    """Favorites session only — ChatGPT auth is client-side (CodexAuth)."""

    payload: dict[str, Any] = {"userSignedIn": False}

    user_id = session.get("user_id")

    if user_id and ms_store.get_user(project_root, user_id):

        payload.update(_favorites_payload(project_root, user_id))

    return payload





def login_demo_user(project_root: Path, slug: str) -> dict[str, Any]:

    key = (slug or "").strip().lower()

    entry = DEMO_USERS.get(key)

    if not entry:

        raise ValueError(f"Unknown user: {slug}")

    user_id, display_name = entry

    ms_store.upsert_user(project_root, user_id, display_name=display_name)

    session["user_id"] = user_id

    session.permanent = True

    return auth_payload(project_root)





def current_user_id() -> str | None:

    return session.get("user_id")





def require_user_id() -> str | None:

    uid = current_user_id()

    return uid if uid else None





def logout_user(project_root: Path) -> None:

    """Clear favorites session only."""

    session.pop("user_id", None)


