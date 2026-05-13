"""极简 Ollama 原生调用：发送 hi，观察是否在约 2 分钟内返回 / minimal native Ollama call with ``hi`` (~2 min budget)."""

from langchain_ollama import OllamaLLM
import time

print("开始测试 Ollama 原生 API (qwen3.5:9b)")
print("使用 reasoning=False 禁用思考模式")
print("=" * 50)

start = time.time()

try:
    # 创建客户端；reasoning=False 关闭 thinking / client with ``reasoning=False`` to disable thinking.
    llm = OllamaLLM(
        model="qwen3.5:9b",
        base_url="http://localhost:11434",
        temperature=0.5,
        reasoning=False,  # 关闭思考模式 / disable thinking mode
    )

    print(f"[{time.time()-start:.1f}s] 客户端创建成功")
    print(f"  reasoning 属性: {llm.reasoning}")
    print(f"[{time.time()-start:.1f}s] 发送消息: hi")

    # 单次 invoke / single ``invoke``.
    response = llm.invoke("hi")

    elapsed = time.time() - start
    print(f"[{elapsed:.1f}s] 收到回复:")
    print(f"  {repr(response[:100])}")
    print(f"\n总计耗时: {elapsed:.1f} 秒")

    if elapsed < 5:
        print("成功: 思考模式已关闭（响应 < 5秒）")
    elif elapsed < 30:
        print("警告: 响应较慢（5-30秒），可能仍有问题")
    else:
        print("警告: 超过 30 秒，思考模式可能仍在运行！")

except Exception as e:
    print(f"错误: {e}")
    import traceback
    traceback.print_exc()
