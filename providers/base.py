import abc
from typing import List, Dict, Any, Optional, Tuple
from core import utils
from core.models import Article, Feed

class RSSProvider(abc.ABC):
    """Abstract base class for RSS providers (Local, Feedly, etc.)"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config

    @abc.abstractmethod
    def get_name(self) -> str:
        pass

    @abc.abstractmethod
    def refresh(self, progress_cb=None, force: bool = False) -> bool:
        """
        Triggers a sync/refresh of feeds.
        progress_cb: optional callable accepting a feed-state dict per completed feed.
        force: if True, providers should ignore cache headers (ETag/Last-Modified) and force fetch.
        """
        pass

    def should_force_startup_refresh(self) -> bool:
        """Whether the first refresh after launch should bypass conditional caching.

        Conditional GET (ETag/If-Modified-Since) saves bandwidth but many feed
        servers return a spurious 304, so freshly opening the app can leave some
        feeds stale until a manual force-refresh. Providers where forcing is cheap
        (e.g. the local provider, one request per feed) override this to True so the
        startup refresh always pulls current content. Hosted providers that would
        fan out into per-feed requests (e.g. Miniflux) should leave this False.
        """
        return False

    def refresh_feed(self, feed_id: str, progress_cb=None) -> bool:
        """
        Triggers a sync/refresh of a single feed.
        """
        return False

    def refresh_feeds_by_ids(self, feed_ids, progress_cb=None, force: bool = True) -> bool:
        """
        Triggers a sync/refresh for a specific set of feeds.

        Providers with a native/batched endpoint should override this. The default
        uses refresh_feed so targeted UI actions work consistently where possible.
        """
        ok = True
        seen = set()
        for raw_id in list(feed_ids or []):
            feed_id = str(raw_id or "").strip()
            if not feed_id or feed_id in seen:
                continue
            seen.add(feed_id)
            if not self.refresh_feed(feed_id, progress_cb=progress_cb):
                ok = False
        return ok

    def _emit_progress(self, progress_cb, state) -> None:
        if progress_cb is None:
            return
        try:
            progress_cb(state)
        except Exception:
            pass

    @abc.abstractmethod
    def get_feeds(self) -> List[Feed]:
        pass

    @abc.abstractmethod
    def get_articles(self, feed_id: str) -> List[Article]:
        pass

    # Favorites are optional and currently implemented for the Local provider.
    def supports_favorites(self) -> bool:
        return False

    def toggle_favorite(self, article_id: str):
        """Toggle an article's favorite state.

        Returns:
            bool: new favorite state
            None: unsupported or article not found
        """
        return None

    def set_favorite(self, article_id: str, is_favorite: bool) -> bool:
        """Set favorite state for an article (optional)."""
        return False

    def get_articles_page(self, feed_id: str, offset: int = 0, limit: int = 200) -> Tuple[List[Article], int]:
        """Optional pagination helper.

        Providers that can do server-side paging should override this for speed.
        Default implementation calls get_articles() and slices the result.
        """
        articles = self.get_articles(feed_id) or []
        total = len(articles)
        if offset < 0:
            offset = 0
        if limit is None or int(limit) <= 0:
            return [], total
        limit = int(limit)
        return articles[offset:offset + limit], total

    # Optional: providers can override for fast single-article lookup.
    def get_article_by_id(self, article_id: str) -> Optional[Article]:
        return None

    def get_feed_errors(self) -> List[Dict[str, Any]]:
        """Return feeds whose most recent update attempt failed (issue #32).

        Each entry is a dict with at least: id, title, url, category,
        last_error, last_error_at (epoch seconds or None), last_success_at, and
        consecutive_failures. Providers without per-feed client-side error
        tracking (e.g. hosted services that sync server-side) return [].
        """
        return []

    @abc.abstractmethod
    def mark_read(self, article_id: str) -> bool:
        pass

    @abc.abstractmethod
    def mark_unread(self, article_id: str) -> bool:
        pass

    def mark_read_batch(self, article_ids: List[str]) -> bool:
        """Default implementation: loop over single mark_read."""
        success = True
        for aid in article_ids:
            if not self.mark_read(aid):
                success = False
        return success

    # Optional: providers can override to mark all items in a view (feed/category/all).
    def mark_all_read(self, feed_id: str) -> bool:
        return False
    
    @abc.abstractmethod
    def add_feed(self, url: str, category: str = None) -> bool:
        pass
    
    @abc.abstractmethod
    def remove_feed(self, feed_id: str) -> bool:
        pass

    # Optional: providers that allow editing feed metadata can override.
    def supports_feed_edit(self) -> bool:
        return False

    def supports_feed_url_update(self) -> bool:
        return False

    def update_feed(self, feed_id: str, title: str = None, url: str = None, category: str = None) -> bool:
        return False

    # Optional: providers may support resetting a user-customized title back to provider-managed/default.
    def supports_feed_title_reset(self) -> bool:
        return False

    def reset_feed_title(self, feed_id: str) -> bool:
        return False
        
    def import_opml(self, path: str, target_category: str = None) -> bool:
        """Default implementation using utils.parse_opml and add_feed."""
        count = 0
        for title, url, category in utils.parse_opml(path):
            cat = target_category if target_category else category
            if self.add_feed(url, cat):
                count += 1
        return count > 0
        
    def export_opml(self, path: str) -> bool:
        """Default implementation using get_feeds and utils.write_opml."""
        feeds = self.get_feeds()
        return utils.write_opml(feeds, path)

    @abc.abstractmethod
    def get_categories(self) -> List[str]:
        """Returns a list of category names."""
        pass

    @abc.abstractmethod
    def add_category(self, title: str, parent_title: str = None) -> bool:
        pass

    @abc.abstractmethod
    def rename_category(self, old_title: str, new_title: str) -> bool:
        pass

    @abc.abstractmethod
    def delete_category(self, title: str) -> bool:
        pass

    def supports_subcategories(self) -> bool:
        """True if this provider supports nested categories (folders within
        folders). Flat providers (most hosted services) return False so the UI
        never offers subcategory creation and nesting is never simulated."""
        return False

    def get_category_hierarchy(self) -> dict:
        """Return {category_path: parent_path} mapping. Providers that do not
        support nesting are flat, so return an empty mapping (every category is
        top-level) regardless of any stale local rows."""
        if not self.supports_subcategories():
            return {}
        from core.db import get_category_hierarchy
        return get_category_hierarchy()

    # Optional: providers that offer server-side "fetch original content" can override this.
    def fetch_full_content(self, article_id: str, url: str = ""):
        return None

    # Optional: providers can implement chapter fetching for specific articles.
    def get_article_chapters(self, article_id: str) -> List[Dict]:
        return utils.get_chapters_from_db(article_id)

    # Optional: providers can implement article deletion.
    def supports_article_delete(self) -> bool:
        return False

    def delete_article(self, article_id: str) -> bool:
        return False

    # Optional: providers that preserve deleted items (a restorable "Deleted
    # Articles" view) can override these. The local provider snapshots deletions
    # into its tombstone table; hosted providers delete server-side and cannot
    # restore, so they leave this off.
    def supports_restore_deleted(self) -> bool:
        return False

    def restore_article(self, article_id: str, feed_id: str | None = None) -> bool:
        _ = feed_id
        return False

    # Optional: Smart Folders (rule-based virtual folders). Local-only feature;
    # hosted providers keep it off since their articles are not in the local table.
    def supports_smart_folders(self) -> bool:
        return False

    def get_smart_folders(self):
        return []

    def create_smart_folder(self, name, rule):
        return None

    def update_smart_folder(self, folder_id, name=None, rule=None):
        return False

    def delete_smart_folder(self, folder_id):
        return False
