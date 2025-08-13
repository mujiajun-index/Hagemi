import json
import logging
import threading
import schedule
import time

logger = logging.getLogger('my_logger')

API_MAPPINGS_FILE = "app/api_mappings.json"
api_mappings = {}
access_keys = {}

ACCESS_KEYS_FILE = "app/access_keys.json"
access_keys_lock = threading.Lock()

def load_access_keys():
    """从 JSON 文件加载访问密钥到全局变量"""
    global access_keys
    try:
        with open(ACCESS_KEYS_FILE, 'r', encoding='utf-8') as f:
            access_keys = json.load(f)
        logger.info(f"成功加载 访问密钥: {len(access_keys)} 个")
    except (FileNotFoundError, json.JSONDecodeError):
        logger.warning(f"未找到或无法解析 {ACCESS_KEYS_FILE}，将创建新文件。")
        access_keys = {}
        save_access_keys()

def save_access_keys():
    """
    将当前的访问密钥保存到 JSON 文件。
    注意：此函数不处理锁，调用方必须确保在线程安全的环境中调用。
    """
    with open(ACCESS_KEYS_FILE, 'w', encoding='utf-8') as f:
        json.dump(access_keys, f, indent=4, ensure_ascii=False)

def get_access_keys():
    """返回当前的访问密钥"""
    return access_keys

def load_api_mappings():
    """从 JSON 文件加载 API 映射到全局变量"""
    global api_mappings
    try:
        with open(API_MAPPINGS_FILE, 'r', encoding='utf-8') as f:
            api_mappings = json.load(f)
        logger.info(f"成功加载 API 映射: {len(api_mappings)} 条规则")
    except (FileNotFoundError, json.JSONDecodeError):
        logger.warning(f"未找到或无法解析 {API_MAPPINGS_FILE}，将创建新文件。")
        api_mappings = {}
        save_api_mappings() # 如果文件不存在或无效，则创建一个空的

def save_api_mappings():
    """将当前的 API 映射保存到 JSON 文件"""
    with open(API_MAPPINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(api_mappings, f, indent=4, ensure_ascii=False)

def get_api_mappings():
    """返回当前的 API 映射"""
    return api_mappings

def reset_daily_usage_counts():
    """
    重置启用了每日重置的密钥的使用次数。
    """
    with access_keys_lock:
        logger.info("开始执行每日使用次数重置任务...")
        updated = False
        for key_id, key_data in access_keys.items():
            if key_data.get('reset_daily'):
                if key_data.get('usage_count', 0) != 0:
                    key_data['usage_count'] = 0
                    updated = True
                    logger.info(f"密钥 '{key_data.get('name', key_id)}' 的使用次数已重置。")
        
        if updated:
            save_access_keys()
            logger.info("已保存重置后的访问密钥。")
        else:
            logger.info("没有需要重置使用次数的密钥。")

def schedule_daily_reset():
    """
    安排每日午夜执行重置任务。
    """
    schedule.every().day.at("00:00").do(reset_daily_usage_counts)
    logger.info("已成功安排每日使用次数重置任务。")

    # 在一个单独的线程中运行调度程序，以避免阻塞主线程
    def run_scheduler():
        while True:
            schedule.run_pending()
            time.sleep(60) # 每分钟检查一次

    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()
