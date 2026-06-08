from PIL import Image

from core.app_paths import ASSETS_DIR, WINDOW_ICON_ICO, WINDOW_ICON_JPEG, WINDOW_ICON_JPG, WINDOW_ICON_PNG


SOURCE_CANDIDATES = [WINDOW_ICON_JPG, WINDOW_ICON_PNG, WINDOW_ICON_JPEG]


def main():
    source = next((path for path in SOURCE_CANDIDATES if path.exists()), None)
    if source is None:
        raise FileNotFoundError("Put the bot image in assets as bot_logo.png, bot_logo.jpg, or bot_logo.jpeg")

    image = Image.open(source).convert("RGBA")
    image.save(
        WINDOW_ICON_ICO,
        format="ICO",
        sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)],
    )
    print(f"Created icon: {WINDOW_ICON_ICO}")


if __name__ == "__main__":
    main()
