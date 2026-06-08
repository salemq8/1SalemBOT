import base64
import html
import time

import requests

from .themes import DEFAULT_THEME_NAME, THEMES


BADGE_CACHE_TTL_SECONDS = 1800
REQUEST_TIMEOUT_SECONDS = 15


class ChatRenderer:
    def __init__(
        self,
        *,
        client_id,
        load_token,
        get_user_by_login,
        get_global_chat_badges,
        get_channel_chat_badges,
    ):
        self.client_id = client_id
        self.load_token = load_token
        self.get_user_by_login = get_user_by_login
        self.get_global_chat_badges = get_global_chat_badges
        self.get_channel_chat_badges = get_channel_chat_badges
        self.badge_catalog_cache = {}
        self.image_data_uri_cache = {}
        self.last_badge_catalog_refresh_at = 0.0
        self.requests_session = requests.Session()
        theme = THEMES[DEFAULT_THEME_NAME]
        self.colors = {
            "background": theme.input_bg,
            "text_primary": theme.text_primary,
            "text_secondary": theme.text_secondary,
            "text_muted": theme.text_muted,
            "accent": theme.accent,
            "warning": theme.warning,
            "chip_bg": theme.elevated_card_background,
            "badge_bg": theme.elevated_card_background,
            "badge_text": theme.text_primary,
        }

    def apply_theme(self, theme):
        self.colors = {
            "background": theme.input_bg,
            "text_primary": theme.text_primary,
            "text_secondary": theme.text_secondary,
            "text_muted": theme.text_muted,
            "accent": theme.accent_hover,
            "warning": theme.warning,
            "chip_bg": theme.elevated_card_background,
            "badge_bg": theme.elevated_card_background,
            "badge_text": theme.text_primary,
        }

    def colorize_text(self, text: str):
        return html.escape(text)

    def fetch_image_data_uri(self, url: str, *, allow_network=True):
        if not url:
            return None
        if url in self.image_data_uri_cache:
            return self.image_data_uri_cache[url]
        if not allow_network:
            return None

        try:
            response = self.requests_session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "image/png").split(";")[0]
            encoded = base64.b64encode(response.content).decode("ascii")
            data_uri = f"data:{content_type};base64,{encoded}"
            self.image_data_uri_cache[url] = data_uri
            return data_uri
        except Exception:
            self.image_data_uri_cache[url] = None
            return None

    def ensure_badge_catalogs(self, channel_login: str, *, allow_network=True):
        now = time.time()
        if self.badge_catalog_cache and (now - self.last_badge_catalog_refresh_at) < BADGE_CACHE_TTL_SECONDS:
            return
        if not allow_network:
            return

        token = self.load_token()
        channel_login = (channel_login or "").strip()
        if not token or not channel_login:
            return

        try:
            broadcaster = self.get_user_by_login(self.client_id, token, channel_login)
            if not broadcaster:
                return

            merged_catalog = {}
            for badge_set in self.get_global_chat_badges(self.client_id, token):
                set_id = badge_set.get("set_id")
                if not set_id:
                    continue
                merged_catalog.setdefault(set_id, {})
                for version in badge_set.get("versions", []):
                    merged_catalog[set_id][version.get("id", "")] = version

            for badge_set in self.get_channel_chat_badges(self.client_id, token, broadcaster.get("id", "")):
                set_id = badge_set.get("set_id")
                if not set_id:
                    continue
                merged_catalog.setdefault(set_id, {})
                for version in badge_set.get("versions", []):
                    merged_catalog[set_id][version.get("id", "")] = version

            if merged_catalog:
                self.badge_catalog_cache = merged_catalog
                self.last_badge_catalog_refresh_at = now
        except Exception:
            pass

    def get_badge_data_uri(self, badge, *, allow_network=True):
        if isinstance(badge, str):
            badge = {"set_id": badge, "id": "1", "info": ""}
        set_id = badge.get("set_id", "")
        version_id = badge.get("id", "")
        versions = self.badge_catalog_cache.get(set_id, {})
        version = versions.get(version_id) or versions.get("1")
        if not version:
            return None

        badge_url = version.get("image_url_1x") or version.get("image_url_2x") or version.get("image_url_4x")
        return self.fetch_image_data_uri(badge_url, allow_network=allow_network)

    def get_badge_title(self, badge):
        if isinstance(badge, str):
            badge = {"set_id": badge, "id": "1", "info": ""}
        set_id = badge.get("set_id", "").replace("_", " ").strip()
        version_id = badge.get("id", "").strip()
        info = badge.get("info", "").strip()
        parts = [part for part in [set_id.title(), version_id, info] if part]
        return " ".join(parts) if parts else "Badge"

    def get_emote_image_data_uri(self, fragment, *, allow_network=True):
        emote = fragment.get("emote") or {}
        emote_id = emote.get("id")
        if not emote_id:
            return None

        available_formats = emote.get("format") or []
        preferred_format = "static"
        if "static" not in available_formats and available_formats:
            preferred_format = available_formats[0]

        emote_url = f"https://static-cdn.jtvnw.net/emoticons/v2/{emote_id}/{preferred_format}/dark/1.0"
        return self.fetch_image_data_uri(emote_url, allow_network=allow_network)

    def badge_html(self, badges, channel_login: str, *, fetch_remote_assets=True):
        self.ensure_badge_catalogs(channel_login, allow_network=fetch_remote_assets)
        parts = []
        for badge in badges:
            if isinstance(badge, str):
                badge = {"set_id": badge, "id": "1", "info": ""}
            data_uri = self.get_badge_data_uri(badge, allow_network=fetch_remote_assets)
            title = html.escape(self.get_badge_title(badge))
            if data_uri:
                parts.append(
                    f"<img src=\"{data_uri}\" title=\"{title}\" "
                    f"style=\"width:16px;height:16px;vertical-align:-3px;margin-right:3px;border-radius:3px;display:inline-block;\" />"
                )
            else:
                fallback = html.escape((badge.get('set_id', '') or 'badge')[:3].upper())
                parts.append(
                    f"<span title=\"{title}\" "
                    f"style=\"display:inline-block;min-width:16px;height:16px;line-height:16px;"
                    f"text-align:center;background:{self.colors['badge_bg']};color:{self.colors['badge_text']};border-radius:4px;"
                    f"font-size:8px;font-weight:700;margin-right:3px;vertical-align:-3px;\">{fallback}</span>"
                )
        return "".join(parts)

    def fragments_to_html(self, fragments, fallback_text="", *, fetch_remote_assets=True):
        if not fragments:
            return self.colorize_text(fallback_text)

        output = []
        for fragment in fragments:
            frag_type = fragment.get("type", "text")
            frag_text = fragment.get("text", "")

            if frag_type == "emote":
                data_uri = self.get_emote_image_data_uri(fragment, allow_network=fetch_remote_assets)
                alt_text = html.escape(frag_text)
                if data_uri:
                    output.append(
                        f"<img src=\"{data_uri}\" alt=\"{alt_text}\" title=\"{alt_text}\" "
                        f"style=\"height:20px;width:auto;vertical-align:-5px;margin:0 1px;display:inline-block;\" />"
                    )
                else:
                    output.append(
                        f"<span style='display:inline-block;background:{self.colors['chip_bg']};color:{self.colors['badge_text']};padding:1px 6px;"
                        f"border-radius:9px;font-size:11px;font-weight:700;margin:0 1px;vertical-align:1px;'>"
                        f"{alt_text}</span>"
                    )
            elif frag_type == "mention":
                output.append(f"<span style='color:{self.colors['accent']};font-weight:700;'>{html.escape(frag_text)}</span>")
            elif frag_type == "cheermote":
                output.append(f"<span style='color:{self.colors['warning']};font-weight:700;'>{html.escape(frag_text)}</span>")
            else:
                output.append(self.colorize_text(frag_text))

        return "".join(output)

    def warm_entries(self, entries, channel_login: str):
        self.ensure_badge_catalogs(channel_login, allow_network=True)

        for item in entries:
            for badge in item.get("badges", []):
                self.get_badge_data_uri(badge, allow_network=True)
            for fragment in item.get("fragments", []):
                if fragment.get("type") == "emote":
                    self.get_emote_image_data_uri(fragment, allow_network=True)

    def build_chat_html(self, entries, channel_login: str, *, fetch_remote_assets=True):
        rows = []
        for item in entries:
            time_text = html.escape(item.get("time", ""))
            username = item.get("user", "")
            user_text = html.escape(item.get("display_name") or username)
            raw_text = item.get("text", "")
            badges = item.get("badges", [])
            fragments = item.get("fragments", [])

            rows.append(
                f"""
                <div style="margin-bottom:6px;line-height:1.35;">
                    <span style="color:{self.colors['text_muted']};vertical-align:baseline;">[{time_text}]</span>
                    <span style="display:inline-block;vertical-align:baseline;margin-left:6px;">{self.badge_html(badges, channel_login, fetch_remote_assets=fetch_remote_assets)}</span>
                    <span style="color:{self.colors['text_primary']};font-weight:700;vertical-align:baseline;">{user_text}</span>
                    <span style="color:{self.colors['text_secondary']};vertical-align:baseline;">: {self.fragments_to_html(fragments, raw_text, fetch_remote_assets=fetch_remote_assets)}</span>
                </div>
                """
            )

        return f"""
        <html>
        <body style="background:{self.colors['background']};color:{self.colors['text_secondary']};font-family:Consolas, monospace;font-size:13px;">
            {''.join(rows)}
        </body>
        </html>
        """
