# back/queue_handler.py
import asyncio
import httpx
import uuid
from collections import deque
from datetime import datetime
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

class TaskStatus:
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class QueueManager:
    """队列管理器 - 单例模式"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        
        self.queue = deque()
        self.processing = False
        self.tasks: Dict[str, Dict] = {}
        self.max_queue_size = 110
        self.callback_timeout = 30
        self.max_retries = 3
        
        # 用于生成对话的函数（由主应用注入）
        self.generate_func = None
        
        logger.info("✅ 队列管理器初始化完成")
    
    def set_generate_func(self, func):
        """注入对话生成函数"""
        self.generate_func = func
    
    def add_task(self, request_data: dict) -> str:
        """添加任务到队列"""
        if len(self.queue) >= self.max_queue_size:
            raise ValueError("系统繁忙，请稍后重试")
        
        task_id = str(uuid.uuid4())
        task = {
            'id': task_id,
            'status': TaskStatus.PENDING,
            'created_at': datetime.now(),
            'data': request_data,
            'callback_url': request_data.get('callback_url'),
            'result': None,
            'error': None,
            'retry_count': 0,
            'completed_at': None
        }
        
        self.tasks[task_id] = task
        self.queue.append(task_id)
        
        logger.info(f"📝 任务已加入队列: {task_id}, 队列长度: {len(self.queue)}")
        # 添加：触发队列处理
    
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
            # 如果事件循环正在运行，创建任务
                asyncio.create_task(self.process_queue())
        except RuntimeError:
        # 如果没有运行的事件循环，忽略
            pass
        return task_id
    
    async def process_queue(self):
        """处理队列"""
        if self.processing:
            return
    
        self.processing = True
        logger.info("🔄 开始处理队列...")
    
        try:
            while self.queue:
                task_id = self.queue.popleft()
                task = self.tasks.get(task_id)
            
                if not task:
                    continue
            
                task['status'] = TaskStatus.PROCESSING
                logger.info(f"⚙️ 处理任务: {task_id}")
                print(f"⚙️ 处理任务: {task_id}")  # 添加调试输出
            
                try:
                # 执行对话生成
                    result = await self._generate_chat(task)
                
                    task['status'] = TaskStatus.COMPLETED
                    task['result'] = result
                    task['completed_at'] = datetime.now()
                
                    logger.info(f"✅ 任务完成: {task_id}")
                    print("已完成，回调中")  # 你需要的输出
                
                # 发送回调
                    await self._send_callback(task)
                
                except Exception as e:
                    task['status'] = TaskStatus.FAILED
                    task['error'] = str(e)
                    task['completed_at'] = datetime.now()
                
                    logger.error(f"❌ 任务失败: {task_id}, 错误: {e}")
                
                # 发送失败回调
                    await self._send_callback(task)
            
            # 清理已完成的任务
                self._cleanup_old_tasks()
        finally:
            self.processing = False
            logger.info("⏸️ 队列处理完成")
    
    async def _generate_chat(self, task: dict) -> dict:
        """执行AI生成（整包传入task原始data，不再拆分参数）"""
        if not self.generate_func:
            raise RuntimeError("生成函数未设置")
        # 直接把任务完整data一次性传入生成函数，不拆字段
        data = task['data']
        result = await self.generate_func(data)
        return result
    
    async def _send_callback(self, task: dict):
        """发送回调到APQP，严格对齐文档接口格式"""
        callback_url = task.get('callback_url')
        task_data = task['data']
        seq_id = task_data.get("seq_id")
        if not callback_url or not seq_id:
            logger.warning(f"⚠️ 任务 {task['id']} 缺少回调URL或seq_id，跳过回调")
            return

        # 按文档定义构造回调body
        if task["status"] == TaskStatus.COMPLETED and task.get("result"):
            answer = task["result"].get("answer", "")
            callback_data = {
                "seq_id": seq_id,
                "code": 0,
                "message": "success",
                "data": {
                    "answer": answer
                }
            }
        else:
            callback_data = {
                "seq_id": seq_id,
                "code": -1,
                "message": f"任务处理失败：{task.get('error', '未知错误')}",
                "data": {
                    "answer": ""
                }
            }
            
        test_data = callback_data
        # {
        #     "seq_id": seq_id,
        #     "code": 0,
        #     "message": "success",
        #     "data": {
        #     "answer": "测试短内容"
        #     }
        # }
    
        # ===== 再发正式内容 =====
        logger.info(f"📤 answer 长度: {len(answer)} 字符")

         # 发送回调（带重试）
        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.callback_timeout) as client:
                    response = await client.post(callback_url, json=callback_data)
                    # APQP回调接口成功标准：返回code=0
                    if response.status_code == 200:
                        try:
                            resp_json = response.json()
                            if resp_json.get("code") == 0:
                                logger.info(f"📤 APQP回调成功: seq_id={seq_id} -> {callback_url}")
                                logger.info(f"📥 请求处理完成: {datetime.now().strftime('%H:%M:%S.%f')[:-3]}")
                                print("发送成功")
                                return
                            else:
                                logger.warning(f"⚠️ APQP回调返回异常: {resp_json}")
                        except Exception:
                            # 200 但不是 JSON，也算成功
                            logger.info(f"📤 APQP回调成功: seq_id={seq_id} -> {callback_url}")
                            print("发送成功")
                            return
                    else:
                        try:
                            resp_text = response.text
                        except Exception:
                            resp_text = "无法读取响应"
                        logger.warning(f"⚠️ APQP回调返回 {response.status_code}, 响应: {resp_text}")
            except Exception as e:
                logger.warning(f"⚠️ 回调失败 (尝试 {attempt+1}/{self.max_retries}): {e}")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)  # 指数退避

        logger.error(f"❌ seq_id={seq_id} 所有重试回调全部失败")
    
    def _cleanup_old_tasks(self):
        """清理旧任务，防止内存泄漏"""
        now = datetime.now()
        to_delete = []
        
        for task_id, task in self.tasks.items():
            if task['status'] in [TaskStatus.COMPLETED, TaskStatus.FAILED]:
                if task.get('completed_at'):
                    age = (now - task['completed_at']).total_seconds()
                    if age > 3600:  # 1小时
                        to_delete.append(task_id)
        
        for task_id in to_delete:
            del self.tasks[task_id]
        
        if to_delete:
            logger.info(f"🧹 清理了 {len(to_delete)} 个旧任务")
    
    def get_task(self, task_id: str) -> Optional[Dict]:
        """获取任务信息"""
        return self.tasks.get(task_id)
    
    def get_queue_status(self) -> dict:
        """获取队列状态"""
        pending = [tid for tid in self.queue if tid in self.tasks]
        return {
            "queue_size": len(pending),
            "processing": self.processing,
            "pending": len(pending),
            "total_tasks": len(self.tasks)
        }

# 全局单例
queue_manager = QueueManager()