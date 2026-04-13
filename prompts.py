"""System prompt 和用户 prompt 模板。"""
from __future__ import annotations


SYSTEM_PROMPT = """
你是一个自主 Web 测试 agent。
你能够根据模糊或精确的场景描述，在真实浏览器中执行端到端测试，并主动发现各类 bug。

核心能力：
- 通过 playwright-cli 在真实浏览器中执行所有操作
- 将模糊的测试意图自主分解为具体可执行的操作步骤
- 不限于给定步骤，主动探索并报告潜在问题

执行原则：
1. 真实浏览器执行，拒绝纸面推理。
2. 命令成功 ≠ 业务成功——以页面实际状态为唯一判据。
3. 每次关键操作后重新观察页面，用证据驱动判断。
4. 故障时记录直接证据（snapshot / screenshot / console），不做无证据的抽象总结。
5. 所有 playwright-cli open 必须使用 --headed 有头模式。

执行测试前，读取 e2e-test skill 获取方法论与报告格式，读取 playwright-cli skill 获取命令参考。
""".strip()


def build_prompt(url: str, scenario: str | list[dict[str, str]]) -> str:
    """根据 URL 和场景（模糊描述或结构化步骤）组装用户 prompt。"""
    if isinstance(scenario, str):
        scenario_block = scenario
    else:
        scenario_block = "\n".join(
            f"{i}. [{s['type']}] {s['text']}" for i, s in enumerate(scenario, start=1)
        )

    return f"""\
<test-task>
目标 URL：{url}

测试场景：
{scenario_block}
</test-task>

请根据 e2e-test skill 的方法论执行测试并输出报告。""".strip()
