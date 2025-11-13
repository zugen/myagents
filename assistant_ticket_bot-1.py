import os
import asyncio
from typing import Optional
import dashscope
from qwen_agent.agents import Assistant
from qwen_agent.gui import WebUI
import pandas as pd
from sqlalchemy import create_engine
from qwen_agent.tools.base import BaseTool, register_tool

# 定义资源文件根目录
ROOT_RESOURCE = os.path.join(os.path.dirname(__file__), 'resource')

# 配置 DashScope
dashscope.api_key = os.getenv('DASHSCOPE_API_KEY', '')  # 从环境变量获取 API Key
dashscope.timeout = 5  # 设置超时时间为 30 秒
"""
dashscope.api_key 的配置虽然看起来没有被直接传递到某个函数或类中，但它实际上是通过 全局配置 的方式被 qwen_agent 库内部使用的。
"""

# ====== 门票助手 system prompt 和函数描述 ======
system_prompt = """我是门票助手，以下是关于门票订单表相关的字段，我可能会编写对应的SQL，对数据进行查询
-- 门票订单表
CREATE TABLE tkt_orders (
    order_time DATETIME,             -- 订单日期
    account_id INT,                  -- 预定用户ID
    gov_id VARCHAR(18),              -- 商品使用人ID（身份证号）
    gender VARCHAR(10),              -- 使用人性别
    age INT,                         -- 年龄
    province VARCHAR(30),           -- 使用人省份
    SKU VARCHAR(100),                -- 商品SKU名
    product_serial_no VARCHAR(30),  -- 商品ID
    eco_main_order_id VARCHAR(20),  -- 订单ID
    sales_channel VARCHAR(20),      -- 销售渠道
    status VARCHAR(30),             -- 商品状态
    order_value DECIMAL(10,2),       -- 订单金额
    quantity INT                     -- 商品数量
);
一日门票，对应多种SKU：
Universal Studios Beijing One-Day Dated Ticket-Standard
Universal Studios Beijing One-Day Dated Ticket-Child
Universal Studios Beijing One-Day Dated Ticket-Senior
二日门票，对应多种SKU：
USB 1.5-Day Dated Ticket Standard
USB 1.5-Day Dated Ticket Discounted
一日门票、二日门票查询：
SUM(CASE WHEN SKU LIKE 'Universal Studios Beijing One-Day%' THEN quantity ELSE 0 END) AS one_day_ticket_sales,
SUM(CASE WHEN SKU LIKE 'USB%' THEN quantity ELSE 0 END) AS two_day_ticket_sales
我将回答用户关于门票相关的问题
"""

# ====== exc_sql 工具类实现,这个工具是自己写的，使用来执行查询sql的！而不是生成sql的，sql何时生成的，见课程笔记文档里 ======
# ======在运行bot.run()时，bot会根据system_prompt理解用户意图，生成sql，然后调用这个工具执行sql查询，并返回结果=======
@register_tool('exc_sql')
class ExcSQLTool(BaseTool):
    """
    SQL查询工具，执行传入的SQL语句并返回结果。
    """
    # `description` 用于告诉智能体该工具的功能。
    description = '对于生成的SQL，进行SQL查询'
    # `parameters` 告诉智能体该工具有哪些输入参数。
    parameters = [{
        'name': 'sql_input',
        'type': 'string',
        'description': '生成的SQL语句',  #什么时候生成的？
        'required': True
    }]

    def call(self, params: str, **kwargs) -> str:
        import json
        args = json.loads(params)
        sql_input = args['sql_input']
        database = args.get('database', 'ubr') #这里是向字典里添加一个键值对，如果不存在，就添加一个键值对，如果存在，就修改值。
        # 创建数据库连接
        engine = create_engine(
            #f'mysql+mysqlconnector://student123:student321@rm-uf6z891lon6dxuqblqo.mysql.rds.aliyuncs.com:3306/{database}?charset=utf8mb4',
            f'mysql+pymysql://student123:student321@rm-uf6z891lon6dxuqblqo.mysql.rds.aliyuncs.com:3306/{database}?charset=utf8mb4',
            connect_args={'connect_timeout': 10}, pool_size=10, max_overflow=20
        )
        try:
            # 使用 text() 包装 SQL 语句，避免 pymysql 的字符串格式化问题
            from sqlalchemy import text
            df = pd.read_sql(text(sql_input), engine)  # 使用 pandas 读取 SQL 查询结果，这个方法很牛！
            # 返回前10行，防止数据过多
            return df.head(10).to_markdown(index=False)  #居然能直接转成markdown格式！牛！
        except Exception as e:
            # 提供详细的异常信息
            import traceback
            error_details = traceback.format_exc()
            
            print(f"-----ERROR: SQL执行失败")
            print(f"-----ERROR: 异常类型: {type(e).__name__}")
            print(f"----ERROR: 异常消息: {str(e)}")
            print(f"-----ERROR: 完整堆栈跟踪:-----")
            print(error_details)
            
            return f"-----SQL执行出错: {str(e)}\n详细错误信息: {error_details}"

# ====== 初始化门票助手服务 ======
def init_agent_service():
    """初始化门票助手服务"""
    llm_cfg = {
        'model': 'qwen-turbo-latest',
        'timeout': 30,
        'retry_count': 3,
    }
    try:
        bot = Assistant(
            llm=llm_cfg,
            name='门票助手',
            description='门票查询与订单分析',
            system_message=system_prompt,
            function_list=['exc_sql'],  # 只传工具名字符串
        )
        print("助手初始化成功！")
        return bot
    except Exception as e:
        print(f"助手初始化失败: {str(e)}")
        raise

def app_tui():
    """终端交互模式
    
    提供命令行交互界面，支持：
    - 连续对话
    - 文件输入
    - 实时响应
    """
    try:
        # 初始化助手
        bot = init_agent_service()

        # 对话历史
        messages = []
        while True:  #我注释的，
            try:
                # 获取用户输入
                query = input('user question: ')
                # 获取可选的文件输入
                file = input('file url (press enter if no file): ').strip()
                
                # 输入验证
                if not query:
                    print('user question cannot be empty！')
                    #continue
                    
                # 构建消息
                if not file:
                    messages.append({'role': 'user', 'content': query})
                else:
                    messages.append({'role': 'user', 'content': [{'text': query}, {'file': file}]})

                print("正在处理您的请求...")
                # 运行助手并处理响应
                response = []
                for response in bot.run(messages):
                    print('bot response lenth:', len(response))  #我加的。这里应该打印 bot.run(messages)的
                    #print('bot response:', response[0]['extra'])
                    #print('bot response:', response[0]['function_call'])
                    print('========bot response:=======', response)
                messages.extend(response)  #上面的while循环好像是为了每循环一次把response加入到这个message,然后下次循环的时候把这个message传给bot.run(messages)，实现连续对话的功能。？
            except Exception as e:
                print(f"处理请求时出错: {str(e)}")
                print("请重试或输入新的问题")
    except Exception as e:
        print(f"启动终端模式失败: {str(e)}")


def app_gui():
    """图形界面模式，提供 Web 图形界面"""
    try:
        print("正在启动 Web 界面...")
        # 初始化助手
        bot = init_agent_service()
        # 配置聊天界面，列举3个典型门票查询问题
        chatbot_config = {
            'prompt.suggestions': [
                '2023年4、5、6月一日门票，二日门票的销量多少？帮我按照周进行统计',
                '2023年7月的不同省份的入园人数统计',
                '帮我查看2023年10月1-7日销售渠道订单金额排名',
            ]
        }
        print("Web 界面准备就绪，正在启动服务...")
        # 启动 Web 界面
        WebUI(
            bot,
            chatbot_config=chatbot_config
        ).run()
    except Exception as e:
        print(f"启动 Web 界面失败: {str(e)}")
        print("请检查网络连接和 API Key 配置")


if __name__ == '__main__':
    # 运行模式选择
    app_gui()          # 图形界面模式（默认）
    #app_tui()         # 终端交互模式
