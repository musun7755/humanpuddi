"""依序測試 HexingBot 的四個 Discord Webhook。"""

from discord_notify import send_discord_message


TEST_MESSAGES = {
    "log": "HexingBot log 測試成功。@humanpuddi 的本機通知系統已啟動。",
    "error": "HexingBot error 測試成功。這裡之後會放錯誤通知。",
    "published": "HexingBot published 測試成功。這裡之後會放已發布紀錄。",
    "review": "HexingBot review 測試成功。這裡之後會放每日候選貼文、Flow prompt、審核提醒。",
}


def main() -> int:
    failed_channels = []

    print("開始測試四個 Discord Webhook……")
    for channel, message in TEST_MESSAGES.items():
        try:
            send_discord_message(channel, message)
        except (RuntimeError, ValueError) as exc:
            failed_channels.append(channel)
            print(f"[失敗] {channel}: {exc}")
        else:
            print(f"[成功] {channel}: 測試訊息已送出。")

    if failed_channels:
        print(f"\n測試未全部通過。失敗頻道：{', '.join(failed_channels)}")
        return 1

    print("\n四個 Discord Webhook 全部測試成功。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

