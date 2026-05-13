"""
测试 Ollama 原生 API（qwen3.5），不跑完整 paper 流水线 / exercise Ollama native API without full paper pipeline.
用于快速验证双后端是否正常 / quick check for dual-backend wiring.
"""

import sys
from pathlib import Path

# 将项目根加入 path，便于导入 / add project root for imports.
sys.path.insert(0, str(Path(__file__).parent))

from langgraph_nodes import (
    OllamaStructuredLLM,
    OllamaReviewerChain,
    OllamaEditorChain,
    OllamaCriticChain,
    ReviewOutput,
    EditorOutput,
    ScoreOutput,
)
from langgraph_state import Issue


def test_ollama_native_basic():
    """基本 Ollama 原生客户端创建 / basic Ollama native client creation."""
    print("=" * 60)
    print("测试 1: 创建 OllamaStructuredLLM 客户端")
    print("=" * 60)

    try:
        llm = OllamaStructuredLLM(
            model="qwen3.5:9b",
            base_url="http://localhost:11434",
            temperature=0.5,
            disable_thinking=True,
            role="test",
        )
        print(f"[OK] 客户端创建成功")
        print(f"   模型: {llm.model}")
        print(f"   禁用思考模式: {llm.disable_thinking}")
    except Exception as e:
        print(f"[ERROR] 客户端创建失败: {e}")
        return False

    return True


def test_ollama_reviewer():
    """审稿链 smoke 测试 / reviewer chain smoke test."""
    print("\n" + "=" * 60)
    print("测试 2: OllamaReviewerChain（审稿）")
    print("=" * 60)

    try:
        llm = OllamaStructuredLLM(
            model="qwen3.5:9b",
            base_url="http://localhost:11434",
            temperature=0.1,
            disable_thinking=True,
            role="reviewer",
        )
        chain = OllamaReviewerChain(llm)

        # 最小输入样例 / minimal sample input.
        test_input = {
            "title": "Introduction",
            "content": "This is a test paragraph with some grammar error.",
        }

        print("正在调用审稿链（可能需要几十秒）...")
        result = chain.invoke(test_input)

        print(f"[OK] 审稿成功")
        print(f"   发现问题数: {len(result.issues)}")
        for i, issue in enumerate(result.issues[:3], 1):
            print(f"   问题 {i}: {issue.problem} (严重性: {issue.severity})")

        return True
    except Exception as e:
        print(f"[ERROR] 审稿失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_ollama_editor():
    """编辑链 smoke 测试 / editor chain smoke test."""
    print("\n" + "=" * 60)
    print("测试 3: OllamaEditorChain（编辑）")
    print("=" * 60)

    try:
        llm = OllamaStructuredLLM(
            model="qwen3.5:9b",
            base_url="http://localhost:11434",
            temperature=0.7,
            disable_thinking=True,
            role="editor",
        )
        chain = OllamaEditorChain(llm)

        # 最小输入样例 / minimal sample input.
        test_issues = [
            Issue(section_id="sec_0", problem="Grammar error", severity="medium", span=None),
        ]
        test_input = {
            "title": "Introduction",
            "content": "This is a test paragraph with some grammar error.",
            "issues": test_issues,
        }

        print("正在调用编辑链（可能需要几十秒）...")
        result = chain.invoke(test_input)

        print(f"[OK] 编辑成功")
        print(f"   输出长度: {len(result.refined_latex)} 字符")
        print(f"   前 100 字符: {result.refined_latex[:100]}...")

        return True
    except Exception as e:
        print(f"[ERROR] 编辑失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_ollama_critic():
    """评分链 smoke 测试 / critic chain smoke test."""
    print("\n" + "=" * 60)
    print("测试 4: OllamaCriticChain（评分）")
    print("=" * 60)

    try:
        llm = OllamaStructuredLLM(
            model="qwen3.5:9b",
            base_url="http://localhost:11434",
            temperature=0.0,
            disable_thinking=True,
            role="critic",
        )
        chain = OllamaCriticChain(llm)

        # 最小输入样例 / minimal sample input.
        test_input = {
            "before": "This is original text.",
            "after": "This is improved text with better grammar.",
        }

        print("正在调用评分链（可能需要几十秒）...")
        result = chain.invoke(test_input)

        print(f"[OK] 评分成功")
        print(f"   分数: {result.score:.2f}")

        return True
    except Exception as e:
        print(f"[ERROR] 评分失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """运行本文件内全部手动测试 / run all manual tests in this module."""
    print("\n" + "=" * 60)
    print("Ollama 原生 API 测试（qwen3.5:9b）")
    print("=" * 60)
    print("注意：此测试直接调用 Ollama 原生 API，不使用 OpenAI 兼容接口")
    print("      测试会自动设置 think: false 关闭 Qwen3.5 的思考模式")
    print()

    # 探测本机 Ollama 是否可用 / probe local Ollama availability.
    try:
        from langchain_ollama import OllamaLLM
        print("[OK] langchain-ollama 已安装")
    except ImportError:
        print("[ERROR] 请先安装: pip install langchain-ollama")
        sys.exit(1)

    # 依次执行各测试 / run each test function.
    results = []

    results.append(("基本客户端", test_ollama_native_basic()))
    results.append(("审稿链", test_ollama_reviewer()))
    results.append(("编辑链", test_ollama_editor()))
    results.append(("评分链", test_ollama_critic()))

    # 打印汇总 / print summary.
    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)

    passed = sum(1 for _, r in results if r)
    total = len(results)

    for name, result in results:
        status = "[PASS]" if result else "[FAIL]"
        print(f"{name}: {status}")

    print(f"\n总计: {passed}/{total} 通过")

    if passed == total:
        print("\n[PASS] 所有测试通过！Ollama 原生 API 工作正常")
        return 0
    else:
        print("\n[WARNING] 部分测试失败，请检查日志")
        return 1


if __name__ == "__main__":
    sys.exit(main())
