"""用户 prompt 模板。"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from webtestagent.core.session import ResolvedSessionState


def build_prompt(
    url: str,
    scenario: str | list[dict[str, str]],
    *,
    outputs_dir: str,
    session_state: ResolvedSessionState | None = None,
) -> str:
    """根据 URL 和场景（模糊描述或结构化步骤）组装用户 prompt。"""
    if isinstance(scenario, str):
        scenario_block = scenario
    else:
        scenario_block = "\n".join(
            f"{i}. [{s['type']}] {s['text']}" for i, s in enumerate(scenario, start=1)
        )

    prompt = f"""\
<test-task>
目标 URL：{url}

测试场景：
{scenario_block}

输出目录：
{outputs_dir}
</test-task>

请根据 e2e-test skill 的方法论执行测试并输出报告。
优先使用 capture_snapshot 获取页面结构；该工具会自动同时保存一张截图，并在返回结果中带上 screenshot 路径。capture_screenshot 仅在你认为需要额外截图时再调用；其余交互优先使用 playwright-cli 原生命令。对于 12306 这类城市联想框，优先鼠标点击候选项，不要默认用 ArrowDown / Enter 选择。对大结果常常落盘，并通过文件系统工具按需读取原始文件。"""

    # 注入 session 上下文
    if session_state is not None:
        if session_state.load_applied:
            prompt += (
                f"\n\n注意：本次运行已自动导入站点 {session_state.site_id} 的登录态"
                f"（账号：{session_state.account_id or '_default'}）。"
                "如果页面已处于登录状态，请直接继续测试，不需要重新登录。"
            )
        elif session_state.enabled_load and not session_state.load_applied:
            prompt += (
                "\n\n注意：本次运行尝试自动导入登录态但未成功"
                f"（原因：{session_state.resolved_by}）。"
                "如果测试需要登录，请正常执行登录流程。"
            )

        if session_state.enabled_save:
            prompt += (
                "\n系统将在测试结束后自动保存登录态，你不需要手动执行 state-save。"
            )

    return prompt.strip()
