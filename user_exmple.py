import httpx
from openai import OpenAI

# 创建禁用证书验证的 httpx 客户端
http_client = httpx.Client(verify=False, timeout=30.0)

client = OpenAI(
    api_key="sk-test-client-001",
    base_url="https://frp-fun.com:61208/embed/v1",
    http_client=http_client,
    # 添加自定义请求头（如你的 API 需要 X-Gateway-Key）
    default_headers={"X-Gateway-Key": "Bearer sk-test-client-001"}
)

try:
    response = client.embeddings.create(
        model="Qwen3-Embedding-0.6B",
        input="Linux Nginx Test"
    )
    print(response.data[0].embedding[:10])
finally:
    http_client.close()  # 记得关闭客户端释放资源