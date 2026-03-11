import json
import asyncio
from openjiuwen.core.foundation.tool.mcp.base import MCPTool
from openjiuwen.core.foundation.tool.mcp.client.sse_client import SseClient

# 开发者自定义实现部署weather MCP服务，再创建天气查询插件的MCPTool实例。
async def get_tools():
    mcp_client = SseClient(server_path="http://100.100.135.209:18000/sse", name="MockSseClient")
    print(await mcp_client.connect(timeout=10))
    tool_info_list = await mcp_client.list_tools()
    for tool_info in tool_info_list:
        print("调用成功，返回结果:", tool_info.model_dump_json())
    mcp_tool = MCPTool(mcp_client=mcp_client, tool_info=tool_info_list[0])
    result = await mcp_tool.ainvoke(inputs={"loannr_chkdgt":"1000014003"})
    print(type(result["result"]))
    data = json.loads(result["result"])
    print(type(data))
    print(data)
    await mcp_client._exit_stack.aclose()

if __name__ == "__main__":
    asyncio.run(get_tools())