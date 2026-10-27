"""OpenAI-compatible deterministic MODEL SUBSTITUTE. No paid services or learners."""
import argparse
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
from threading import Lock

counts, lock = Counter(), Lock()


def chat_reply(body):
    messages = body.get("messages", [])
    text = "\n".join(str(m.get("content") or "") for m in messages)
    if body.get("tools"):
        if messages[-1]["role"] == "tool":
            return {"role": "assistant", "content": "资料指出 Depends 声明依赖并由框架注入参数。[1] 可以继续练习巩固。"}, "coach"
        if "练习" in str(messages[-1].get("content", "")):
            profile = json.loads(messages[1]["content"].split("\n", 1)[1])["profile"]
            topic_id = profile["topics"][0]["id"]
            name, args = "create_practice", {"topic_id": topic_id, "topic": "依赖注入", "difficulty": 2}
        else:
            name, args = "search_material", {"query": "Depends 依赖注入"}
        return {"role": "assistant", "content": None, "tool_calls": [
            {"id": "stub-tool", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}, "coach"
    if '"topic_index"' in text:
        data, kind = {"topic_index": 1}, "topic_assignment"
    elif '"topics"' in text:
        data, kind = {"topics": [
            {"name": "依赖注入", "description": "Depends 声明依赖，由框架提供参数。"},
            {"name": "检索增强生成", "description": "检索资料后依据证据生成回答。"},
            {"name": "用户认证", "description": "JWT 表示登录身份，服务端验证资料归属。"}]}, "topic_extraction"
    elif '"option_a"' in text:
        level = re.search(r"难度为\s*(\d)", text)
        data, kind = {"question": "FastAPI 使用哪个函数声明依赖？", "option_a": "Depends",
            "option_b": "print", "option_c": "range", "option_d": "len", "answer": "A",
            "explanation": "资料说明 Depends 声明依赖，由框架注入参数。",
            "difficulty": int(level.group(1)) if level else 2}, "question"
    else:
        kind = "feedback" if "答题数据" in text else "rag"
        return {"role": "assistant", "content": "Depends 声明依赖，由框架调用依赖函数并注入参数。[1]"}, kind
    return {"role": "assistant", "content": json.dumps(data, ensure_ascii=False)}, kind


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass  # Never log prompts, Authorization headers or account data.

    def reply(self, body, status=200):
        content = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        with lock:
            snapshot = dict(counts)
        self.reply({"source": "mocked_provider_http", "model_calls": snapshot})

    def do_POST(self):
        size = int(self.headers.get("Content-Length", "0"))
        if not 0 < size <= 1024*1024:
            return self.reply({"error": "invalid body"}, 413)
        body = json.loads(self.rfile.read(size))
        if self.path.endswith("/embeddings"):
            dimensions = int(body.get("dimensions", 1024))
            inputs = body["input"] if isinstance(body["input"], list) else [body["input"]]
            result = {"object": "list", "model": "stub-embedding", "data": [
                {"object": "embedding", "index": i, "embedding": [1.0]+[0.0]*(dimensions-1)}
                for i in range(len(inputs))], "usage": {"prompt_tokens": 0, "total_tokens": 0}}
            kind = "embedding"
        elif self.path.endswith("/chat/completions"):
            message, kind = chat_reply(body)
            result = {"id": "s5-mock", "object": "chat.completion", "created": 0, "model": "stub-chat",
                "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if message.get("tool_calls") else "stop"}],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}
        else:
            return self.reply({"error": "unsupported stub endpoint"}, 404)
        with lock:
            counts[kind] += 1
        self.reply(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
