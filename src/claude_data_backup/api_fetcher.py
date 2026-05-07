"""Mode A —— 在线 API 全量抓取。

用 sessionKey 直接调 claude.ai 的私有 API。端点和响应结构见 docs/data-formats.md。
"""
from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Callable, Iterator

import requests

from . import paths
from .i18n import t as _

API_BASE = "https://claude.ai/api"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) claudeai/0.14.2 Chrome/124.0.0.0 Electron/30.0.0 Safari/537.36"
)


class ApiError(Exception):
    pass


class ApiFetcher:
    """单线程 claude.ai API 客户端，中断可恢复。"""

    def __init__(self, session_key: str, sleep_between: float = 0.5):
        self.session_key = session_key
        self.sleep_between = sleep_between
        self.sess = requests.Session()
        # 自动检测并应用系统代理
        proxy = paths.detect_system_proxy()
        if proxy:
            self.sess.proxies.update(proxy)
        self.sess.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Cookie": f"sessionKey={session_key}",
            "Referer": "https://claude.ai/chats",
        })

    # ---------- 内部 ----------

    def _get(self, path: str, retries: int = 3) -> dict | list:
        url = f"{API_BASE}{path}"
        backoff = 2.0
        for attempt in range(retries):
            try:
                resp = self.sess.get(url, timeout=30)
                if resp.status_code == 429:
                    time.sleep(min(backoff, 30))
                    backoff *= 2
                    continue
                if resp.status_code == 401 or resp.status_code == 403:
                    raise ApiError(_("api.auth_fail", code=resp.status_code))
                if resp.status_code >= 500:
                    time.sleep(min(backoff, 30))
                    backoff *= 2
                    continue
                resp.raise_for_status()
                return resp.json()
            except requests.exceptions.RequestException as e:
                if attempt == retries - 1:
                    raise ApiError(_("api.request_fail", url=url, error=str(e))) from e
                time.sleep(min(backoff, 30))
                backoff *= 2
        raise ApiError(_("api.max_retries", url=url))

    # ---------- 公共 API ----------

    def probe(self) -> bool:
        """快速判断 sessionKey 是否有效。"""
        try:
            r = self._get("/organizations", retries=1)
            return isinstance(r, list) and len(r) > 0
        except ApiError:
            return False

    def list_organizations(self) -> list[dict]:
        r = self._get("/organizations")
        return r if isinstance(r, list) else []

    def list_conversations(self, org_uuid: str) -> list[dict]:
        """只有 metadata（uuid / name / created_at / updated_at / project_uuid / ...），不含消息内容。"""
        r = self._get(f"/organizations/{org_uuid}/chat_conversations")
        return r if isinstance(r, list) else []

    def list_projects(self, org_uuid: str) -> list[dict]:
        # 先尝试 projects_v2；不支持的账号用 projects
        try:
            r = self._get(f"/organizations/{org_uuid}/projects_v2")
            if isinstance(r, list):
                return r
            if isinstance(r, dict) and "projects" in r:
                return r["projects"]
        except ApiError:
            pass
        try:
            r = self._get(f"/organizations/{org_uuid}/projects")
            return r if isinstance(r, list) else []
        except ApiError:
            return []

    def fetch_conversation(self, org_uuid: str, conv_uuid: str) -> dict:
        """完整对话（含消息树）。"""
        path = (
            f"/organizations/{org_uuid}/chat_conversations/{conv_uuid}"
            "?tree=True&rendering_mode=messages&render_all_tools=true&consistency=eventual"
        )
        r = self._get(path)
        if not isinstance(r, dict):
            raise ApiError(_("api.fetch_error", type=type(r)))
        return r

    # ---------- 流式抓取全量 ----------

    def stream_all(self, org_uuid: str,
                   save_dir: Path | None = None,
                   progress: Callable[[int, int, str], None] | None = None,
                   skip_map: dict[str, str] | None = None) -> Iterator[dict]:
        """一次性抓全量对话。支持中断恢复和增量跳过。

        参数：
            save_dir: 中断恢复目录，已存在的 uuid 会从磁盘读取而非重新抓取。
            skip_map: 增量备份用，{uuid: updated_at}。UUID 在 map 中且 updated_at
                      未变的对话会被跳过（不 yield 也不发 API 请求）。

        yield 每一条完整 conversation dict。
        """
        convs_meta = self.list_conversations(org_uuid)
        total = len(convs_meta)

        # 恢复：已经保存过的跳过
        already: set[str] = set()
        if save_dir:
            save_dir.mkdir(parents=True, exist_ok=True)
            already = {p.stem for p in save_dir.glob("*.json")}

        for idx, meta in enumerate(convs_meta):
            uuid = meta.get("uuid")
            if not uuid:
                continue
            if progress:
                progress(idx, total, meta.get("name", _("renderer.unnamed")))

            # 增量跳过：已备份且未更新的对话直接跳过
            if skip_map and uuid in skip_map:
                remote_updated = meta.get("updated_at", "")
                if skip_map[uuid] == remote_updated:
                    continue

            if uuid in already:
                # 读回来 yield
                if save_dir:
                    try:
                        conv = json.loads((save_dir / f"{uuid}.json").read_text(encoding="utf-8"))
                        yield conv
                        continue
                    except (OSError, ValueError):
                        pass  # 继续重抓
            try:
                conv = self.fetch_conversation(org_uuid, uuid)
                if save_dir:
                    (save_dir / f"{uuid}.json").write_text(
                        json.dumps(conv, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                yield conv
            except ApiError as e:
                # 记录失败、不中断
                if save_dir:
                    failed_path = save_dir / "_failed.jsonl"
                    with open(failed_path, "a", encoding="utf-8") as f:
                        f.write(json.dumps({"uuid": uuid, "error": str(e)},
                                           ensure_ascii=False) + "\n")
                continue
            time.sleep(self.sleep_between)

        if progress:
            progress(total, total, "done")


if __name__ == "__main__":
    from .cookies import get_session_key
    sk = get_session_key()
    if not sk:
        print(_("api.no_key"))
        raise SystemExit(1)
    f = ApiFetcher(sk)
    if not f.probe():
        print(_("api.invalid_key"))
        raise SystemExit(1)
    orgs = f.list_organizations()
    print(f"organizations: {len(orgs)}")
    if orgs:
        convs = f.list_conversations(orgs[0]["uuid"])
        print(f"conversations in first org: {len(convs)}")
