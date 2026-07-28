import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_openai_tools_agent
from langchain_core.prompts import ChatPromptTemplate

# 导入你自己封装好的查询工具
from tools import get_structured_query_tools

# 1. 加载环境变量（把mysql、大模型密钥放.env文件）
load_dotenv()

# 2. 初始化大模型，temperature=0禁止AI编造数据
llm = ChatOpenAI(
    model=os.getenv("MODEL_NAME", "gpt-3.5-turbo"),
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url=os.getenv("OPENAI_BASE_URL"),
    temperature=0  
)

# 3. 加载所有APQP数据库查询工具
tools = get_structured_query_tools()

# 4. 定制业务系统提示词（约束AI只能查表，不能瞎编）
system_prompt = """
你是企业APQP项目管理智能客服，回答用户问题必须严格遵守以下规则：
1. 所有项目相关信息（进度、风险、问题、交付物）只能调用提供的数据库工具查询，绝对不能凭空编造；
2. 用户给出项目编号/项目名称关键词，优先使用 apqp_project_summary 一次性汇总全部维度数据；
3. 工具返回空数据时，直接告知用户「未查询到匹配的项目记录」，不要自行脑补内容；
4. 输出使用制造业专业简洁话术，查询到多条数据请分点清晰展示；
5. 禁止输出不存在的项目ID、风险等级、日期、负责人等业务字段。
"""

prompt = ChatPromptTemplate.from_messages([
    ("system", system_prompt),
    ("human", "{input}"),
    ("placeholder", "{agent_scratchpad}"),
])

# 5. 创建工具调用Agent & 执行器
agent = create_openai_tools_agent(llm, tools, prompt)
agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True)

# 6. 终端交互入口
if __name__ == "__main__":
    print("==== APQP项目查询Demo（方案1 无记忆Agent）====")
    print("输入 exit 退出对话\n")
    while True:
        user_input = input("用户提问：")
        if user_input.strip().lower() == "exit":
            print("会话结束")
            break
        # 执行Agent
        result = agent_executor.invoke({"input": user_input})
        print(f"\nAI回复：\n{result['output']}\n")