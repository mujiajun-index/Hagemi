import json
import logging
import threading

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
    """将当前的访问密钥保存到 JSON 文件（线程安全）"""
    if access_keys_lock.acquire(blocking=False):
        try:
            # 为了确保数据一致性，在写入时复制一份
            keys_to_save = access_keys.copy()
            with open(ACCESS_KEYS_FILE, 'w', encoding='utf-8') as f:
                json.dump(keys_to_save, f, indent=4, ensure_ascii=False)
            logger.info("访问密钥已成功同步到文件。")
        finally:
            access_keys_lock.release()
    else:
        logger.info("另一个线程正在同步访问密钥，跳过本次操作。")

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
    logger.info("API 映射已成功保存。")

def get_api_mappings():
    """返回当前的 API 映射"""
    return api_mappings
