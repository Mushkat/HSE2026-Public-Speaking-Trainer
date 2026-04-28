import importlib


def _assert_import(name: str) -> None:
    importlib.import_module(name)
    print(f"ok import: {name}")


def main() -> None:
    _assert_import("requests")
    from faster_whisper import WhisperModel

    print("ok import: faster_whisper.WhisperModel", WhisperModel.__name__)


if __name__ == "__main__":
    main()
