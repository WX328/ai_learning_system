"""Prepare PRIVATE disposable S5 credentials, never real users or API keys."""
import json
from pathlib import Path
import secrets


def main():
    private = Path(".s5-local")
    private.mkdir(exist_ok=True)
    credentials = private / "acceptance-credentials.json"
    environment = private / "acceptance.env"
    if credentials.exists() or environment.exists():
        raise SystemExit("Private acceptance files already exist; reuse them or choose a fresh workspace.")
    suffix = secrets.token_hex(4)
    accounts = {key: {"username":"s5-"+key+"-"+suffix, "password":secrets.token_urlsafe(24)}
                for key in ("admin","learner","other","browser")}
    credentials.write_text(json.dumps(accounts), encoding="utf-8")
    environment.write_text("\n".join((
        "SECRET_KEY="+secrets.token_urlsafe(48), "DEEPSEEK_API_KEY=engineering-stub-only",
        "DASHSCOPE_API_KEY=engineering-stub-only", "DASHSCOPE_EMBEDDING_BASE_URL=http://model-stub:9000/v1",
        "DASHSCOPE_EMBEDDING_MODEL=text-embedding-v4", "DASHSCOPE_EMBEDDING_DIMENSIONS=1024",
    ))+"\n", encoding="utf-8")
    print("Private synthetic credentials and model-substitute environment created.")


if __name__ == "__main__":
    main()
