"""經 Discord 人工批准後，發布單張或多張圖片 Threads 貼文。"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Final

import requests
from dotenv import load_dotenv

PROJECT_ROOT: Final = Path(__file__).resolve().parent.parent
ENV_FILE: Final = PROJECT_ROOT / ".env"
GRAPH_BASE: Final = "https://graph.threads.net/v1.0"


class ThreadsPublishError(RuntimeError):
    pass


def _config(name: str) -> str:
    load_dotenv(ENV_FILE, override=False)
    value = os.getenv(name, "").strip()
    if not value:
        raise ThreadsPublishError(f"尚未設定 {name}。")
    return value


def _error(response: requests.Response, action: str) -> ThreadsPublishError:
    try:
        detail = response.json().get("error", {}).get("message", response.text)
    except (ValueError, AttributeError):
        detail = response.text
    return ThreadsPublishError(f"Threads {action}失敗。HTTP {response.status_code}：{detail or '未提供錯誤內容'}")


def _wait_until_finished(container_id: str, token: str, action: str) -> None:
    """等待 Meta 處理完一個 media container。"""
    for _ in range(12):
        response = requests.get(
            f"{GRAPH_BASE}/{container_id}",
            params={"fields": "status,error_message", "access_token": token},
            timeout=20,
        )
        if not response.ok:
            raise _error(response, f"查詢{action}處理狀態")
        body = response.json()
        status = str(body.get("status", "")).upper()
        if status == "FINISHED":
            return
        if status in {"ERROR", "EXPIRED"}:
            raise ThreadsPublishError(f"Threads {action}處理失敗：{body.get('error_message') or status}")
        time.sleep(5)
    raise ThreadsPublishError(f"Threads 等待{action}處理逾時，尚未發布。")


def _create_image_container(
    user_id: str,
    image_url: str,
    token: str,
    alt_text: str,
    carousel_item: bool,
    text: str = "",
    topic_tag: str = "",
) -> str:
    data = {
        "media_type": "IMAGE",
        "image_url": image_url,
        "alt_text": alt_text[:1000],
        "access_token": token,
    }
    if carousel_item:
        data["is_carousel_item"] = "true"
    if text:
        data["text"] = text
    if topic_tag:
        data["topic_tag"] = topic_tag
    response = requests.post(f"{GRAPH_BASE}/{user_id}/threads", data=data, timeout=30)
    if not response.ok:
        raise _error(response, "建立圖片 container")
    container_id = str(response.json().get("id", "")).strip()
    if not container_id:
        raise ThreadsPublishError("Threads 沒有回傳圖片 container ID。")
    _wait_until_finished(container_id, token, "圖片")
    return container_id


def publish_image_post(
    text: str,
    image_urls: str | list[str] | tuple[str, ...],
    alt_text: str = "赫湦 Threads 貼文圖片",
    topic_tag: str = "",
) -> str:
    """發布 1～20 張圖片；多張圖片會建立 carousel。"""
    token = _config("THREADS_ACCESS_TOKEN")
    user_id = _config("THREADS_USER_ID")
    if not text.strip():
        raise ThreadsPublishError("貼文內容不可為空白。")
    urls = [image_urls] if isinstance(image_urls, str) else list(image_urls)
    if not 1 <= len(urls) <= 20:
        raise ThreadsPublishError("圖片數量必須介於 1～20 張。")
    if any(not url.startswith("https://") for url in urls):
        raise ThreadsPublishError("圖片必須是公開 HTTPS 網址。")
    topic_tag = topic_tag.strip().lstrip("#").strip()

    if len(urls) == 1:
        creation_id = _create_image_container(
            user_id,
            urls[0],
            token,
            alt_text,
            carousel_item=False,
            text=text.strip(),
            topic_tag=topic_tag,
        )
    else:
        children = [
            _create_image_container(
                user_id, url, token, f"{alt_text} {index}", carousel_item=True
            )
            for index, url in enumerate(urls, start=1)
        ]
        create = requests.post(
            f"{GRAPH_BASE}/{user_id}/threads",
            data={
                "media_type": "CAROUSEL",
                "children": ",".join(children),
                "text": text.strip(),
                "access_token": token,
                **({"topic_tag": topic_tag} if topic_tag else {}),
            },
            timeout=30,
        )
        if not create.ok:
            raise _error(create, "建立多圖貼文")
        creation_id = str(create.json().get("id", "")).strip()
        if not creation_id:
            raise ThreadsPublishError("Threads 沒有回傳 carousel container ID。")
        _wait_until_finished(creation_id, token, "多圖貼文")

    publish = requests.post(
        f"{GRAPH_BASE}/{user_id}/threads_publish",
        data={"creation_id": creation_id, "access_token": token},
        timeout=30,
    )
    if not publish.ok:
        raise _error(publish, "發布")
    post_id = str(publish.json().get("id", "")).strip()
    if not post_id:
        raise ThreadsPublishError("Threads 已接受發布，但沒有回傳貼文 ID。")
    return post_id


def publish_ghost_post(text: str, topic_tag: str = "") -> str:
    """發布一則 24 小時後自動失效的純文字 Threads Ghost post。"""
    token = _config("THREADS_ACCESS_TOKEN")
    user_id = _config("THREADS_USER_ID")
    text = text.strip()
    topic_tag = topic_tag.strip().lstrip("#").strip()
    if not text:
        raise ThreadsPublishError("限時貼文內容不可為空白。")

    data = {
        "media_type": "TEXT",
        "text": text,
        "is_ghost_post": "true",
        "access_token": token,
        **({"topic_tag": topic_tag} if topic_tag else {}),
    }
    create = requests.post(
        f"{GRAPH_BASE}/{user_id}/threads", data=data, timeout=30
    )
    if not create.ok:
        raise _error(create, "建立限時貼文")
    creation_id = str(create.json().get("id", "")).strip()
    if not creation_id:
        raise ThreadsPublishError("Threads 沒有回傳限時貼文 container ID。")
    _wait_until_finished(creation_id, token, "限時貼文")

    publish = requests.post(
        f"{GRAPH_BASE}/{user_id}/threads_publish",
        data={"creation_id": creation_id, "access_token": token},
        timeout=30,
    )
    if not publish.ok:
        raise _error(publish, "發布限時貼文")
    post_id = str(publish.json().get("id", "")).strip()
    if not post_id:
        raise ThreadsPublishError("Threads 已接受限時貼文，但沒有回傳貼文 ID。")
    return post_id


def publish_reply(reply_id: str, text: str) -> str:
    """人工批准後，發布一則 Threads 公開留言回覆。"""
    token = _config("THREADS_ACCESS_TOKEN")
    user_id = _config("THREADS_USER_ID")
    reply_id = reply_id.strip()
    text = text.strip()
    if not reply_id:
        raise ThreadsPublishError("缺少要回覆的 Threads 留言 ID。")
    if not text:
        raise ThreadsPublishError("回覆內容不可為空白。")
    create = requests.post(
        f"{GRAPH_BASE}/{user_id}/threads",
        data={
            "media_type": "TEXT",
            "text": text,
            "reply_to_id": reply_id,
            "access_token": token,
        },
        timeout=30,
    )
    if not create.ok:
        raise _error(create, "建立留言回覆")
    creation_id = str(create.json().get("id", "")).strip()
    if not creation_id:
        raise ThreadsPublishError("Threads 沒有回傳留言回覆 container ID。")
    _wait_until_finished(creation_id, token, "留言回覆")
    publish = requests.post(
        f"{GRAPH_BASE}/{user_id}/threads_publish",
        data={"creation_id": creation_id, "access_token": token},
        timeout=30,
    )
    if not publish.ok:
        raise _error(publish, "發布留言回覆")
    post_id = str(publish.json().get("id", "")).strip()
    if not post_id:
        raise ThreadsPublishError("Threads 已接受留言回覆，但沒有回傳回覆 ID。")
    return post_id
