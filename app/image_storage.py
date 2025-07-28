import os
import base64
import uuid
from datetime import datetime
import time
import logging
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger('my_logger')
from dotenv import load_dotenv
# 加载.env文件中的环境变量
load_dotenv()

# 抽象基类
class ImageStorage(ABC):
    """图片存储的抽象基类，定义了存储图片的接口"""
    
    @abstractmethod
    def save_image(self, mime_type: str, base64_data: str) -> str:
        """保存图片并返回可访问的URL"""
        pass

    @abstractmethod
    def list_images(self, page: int, page_size: int) -> dict:
        """列出存储的图片，支持分页"""
        pass

    @abstractmethod
    def delete_image(self, filename: str) -> bool:
        """删除指定的图片"""
        pass


# 本地存储实现
class LocalImageStorage(ImageStorage):
    """将图片保存到本地文件系统"""
    
    def __init__(self, host_url: str, image_dir: Optional[str] = None):
        """初始化本地存储
        
        Args:
            host_url: 主机URL，用于构建图片访问地址
            image_dir: 图片存储目录，如果为None则使用默认目录
        """
        self.host_url = host_url
        # 如果没有指定目录，使用默认的app/images目录
        if image_dir is None:
            self.image_dir = os.path.join(os.path.dirname(__file__), 'images')
        else:
            self.image_dir = image_dir
        # 确保目录存在
        os.makedirs(self.image_dir, exist_ok=True)
        # 从环境变量获取最大图片数量，默认为1000
        self.max_images = int(os.environ.get('LOCAL_MAX_IMAGE_NUMBER', 1000))
        # 从环境变量获取最大存储大小（MB），默认为1000MB
        self.max_size_mb = int(os.environ.get('LOCAL_MAX_IMAGE_SIZE_MB', 1000))
        self.clean_interval_seconds = int(os.environ.get('LOCAL_CLEAN_INTERVAL_SECONDS', 3600)) # 默认1小时
        self.last_clean_time = 0
    def save_image(self, mime_type: str, base64_data: str) -> str:
        """将Base64编码的图片保存到本地文件系统
        
        Args:
            mime_type: 图片的MIME类型
            base64_data: Base64编码的图片数据
            
        Returns:
            str: 图片的HTTP访问地址
        """
        logger.info(f"保存图片到本地: {self.image_dir}")
        
        # 生成唯一文件名
        file_ext = mime_type.split('/')[-1]
        unique_filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{str(uuid.uuid4())[:8]}.{file_ext}"
        file_path = os.path.join(self.image_dir, unique_filename)
        
        # 解码并保存图片
        image_data = base64.b64decode(base64_data)
        with open(file_path, 'wb') as f:
            f.write(image_data)
        
        # 返回HTTP访问地址
        image_url = f"{self.host_url}/images/{unique_filename}"
        # 保存图片后执行清理（冷却时间内最多执行一次）
        current_time = time.time()
        if current_time - self.last_clean_time > self.clean_interval_seconds:
            self.clean_old_images()
            self.last_clean_time = current_time
        return image_url

    def get_image(self, filename: str):
        """从本地文件系统中获取图片数据
        
        Args:
            filename: 图片文件名
            
        Returns:
            tuple: (base64编码的图片数据, MIME类型) 或 None（如果图片不存在）
        """
        file_path = os.path.join(self.image_dir, filename)
        if os.path.exists(file_path):
            # 获取MIME类型
            file_ext = os.path.splitext(filename)[1].lstrip('.')
            mime_type = f'image/{file_ext}'
            
            # 读取文件并转换为base64
            with open(file_path, 'rb') as f:
                image_data = f.read()
                base64_data = base64.b64encode(image_data).decode('utf-8')
                return base64_data, mime_type
        return None, None

    def clean_old_images(self):
        """根据配置清理本地存储中的旧图片"""
        logger.info("开始自动检查清理本地图片...")
        # 获取所有图片文件，并按修改时间排序
        image_files = []
        for f in os.listdir(self.image_dir):
            file_path = os.path.join(self.image_dir, f)
            if os.path.isfile(file_path):
                try:
                    timestamp = os.path.getmtime(file_path)
                    size = os.path.getsize(file_path)
                    image_files.append((file_path, timestamp, size))
                except OSError as e:
                    logger.warning(f"无法获取文件元数据 {file_path}: {e}")
        image_files.sort(key=lambda x: x[1])  # 按修改时间升序排序

        # 按数量清理
        while len(image_files) > self.max_images:
            if not image_files: # 避免空列表操作
                break
            oldest_file_path = image_files.pop(0)[0]
            try:
                os.remove(oldest_file_path)
                logger.info(f"按数量清理：删除最旧图片 {oldest_file_path}, 当前总数量 {len(image_files)}个")
            except OSError as e:
                logger.error(f"删除文件失败 {oldest_file_path}: {e}")

        # 按大小清理
        current_size_mb = sum([x[2] for x in image_files]) / (1024 * 1024)
        while current_size_mb > self.max_size_mb and len(image_files) > 0:
            if not image_files: # 避免空列表操作
                break
            oldest_file_info = image_files.pop(0)
            oldest_file_path = oldest_file_info[0]
            oldest_file_size = oldest_file_info[2]
            try:
                os.remove(oldest_file_path)
                current_size_mb -= oldest_file_size / (1024 * 1024)
                logger.info(f"按大小清理：删除最旧图片 {oldest_file_path}, 当前总大小 {current_size_mb:.2f}MB")
            except OSError as e:
                logger.error(f"删除文件失败 {oldest_file_path}: {e}")

    def list_images(self, page: int, page_size: int) -> dict:
        """列出本地存储的图片，支持分页"""
        image_files_meta = []
        for f in os.listdir(self.image_dir):
            file_path = os.path.join(self.image_dir, f)
            if os.path.isfile(file_path):
                try:
                    image_files_meta.append({
                        "filename": f,
                        "url": f"{self.host_url}/images/{f}",
                        "created_at": datetime.fromtimestamp(os.path.getmtime(file_path)).isoformat()
                    })
                except OSError as e:
                    logger.warning(f"无法获取文件元数据 {file_path}: {e}")

        # 按创建时间降序排序
        image_files_meta.sort(key=lambda x: x['created_at'], reverse=True)
        
        # 分页
        start = (page - 1) * page_size
        end = start + page_size
        paginated_files = image_files_meta[start:end]
        
        return {
            "images": paginated_files,
            "total": len(image_files_meta),
            "page": page,
            "page_size": page_size
        }

    def delete_image(self, filename: str) -> bool:
        """删除本地存储的指定图片"""
        file_path = os.path.join(self.image_dir, filename)
        if os.path.exists(file_path) and os.path.isfile(file_path):
            try:
                os.remove(file_path)
                logger.info(f"成功删除本地图片: {filename}")
                return True
            except OSError as e:
                logger.error(f"删除本地图片失败 {filename}: {e}")
                return False
        logger.warning(f"尝试删除但文件不存在: {filename}")
        return False

    def get_storage_details(self) -> dict:
        """获取本地存储的使用情况详情"""
        image_files = [f for f in os.listdir(self.image_dir) if os.path.isfile(os.path.join(self.image_dir, f))]
        total_images = len(image_files)
        total_size_bytes = sum(os.path.getsize(os.path.join(self.image_dir, f)) for f in image_files)
        total_size_mb = total_size_bytes / (1024 * 1024)

        return {
            "total_images": total_images,
            "max_images": self.max_images,
            "total_size_mb": round(total_size_mb, 2),
            "max_size_mb": self.max_size_mb,
        }
# 云存储实现（示例，需要根据实际云服务提供商进行实现）
from qiniu import Auth, put_data

class QiniuImageStorage(ImageStorage):
    """将图片保存到七牛云存储服务"""
    
    def __init__(self, credentials: dict):
        """初始化七牛云存储
        Args:
            cloud_provider: 云服务提供商名称
            credentials: 云服务认证信息，包含access_key和secret_key,空间名称,外链域名
        """
        self.credentials = credentials
        self.bucket_name = credentials.get('bucket_name')
        self.bucket_domain = credentials.get('bucket_domain')
        # 初始化七牛云客户端
        self.q = Auth(credentials.get('access_key'), credentials.get('secret_key'))
    
    def save_image(self, mime_type: str, base64_data: str) -> str:
        """将Base64编码的图片保存到七牛云存储
        Args:
            mime_type: 图片的MIME类型
            base64_data: Base64编码的图片数据
        Returns:
            str: 图片的HTTP访问地址
        """
        logger.info(f"保存图片到七牛云存储")
        # 生成唯一文件名
        file_ext = mime_type.split('/')[-1]
        unique_filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{str(uuid.uuid4())[:8]}.{file_ext}"
        # 解码图片数据
        image_data = base64.b64decode(base64_data)
        # 生成上传凭证
        token = self.q.upload_token(self.bucket_name, unique_filename)
        # 上传文件
        ret, info = put_data(
            token,
            unique_filename,
            image_data,
            mime_type=mime_type
        )
        
        if info.status_code == 200:
            # 返回文件的可访问URL
            return f"{self.bucket_domain}/{unique_filename}"
        else:
            logger.error(f"上传失败: {info}")
            raise Exception("上传图片到七牛云失败,请检查配置信息")


# 腾讯云COS存储实现
from qcloud_cos import CosConfig,CosS3Client
import io

# 内存存储实现
class MemoryImageStorage(ImageStorage):
    """将图片保存到内存中，使用环形数组存储，限制最大图片数量"""
    
    def __init__(self, host_url: str):
        """初始化内存存储
        
        Args:
            host_url: 主机URL，用于构建图片访问地址
        """
        self.host_url = host_url
        # 从环境变量获取最大图片数量，默认为1000
        self.max_images = int(os.environ.get('MEMORY_MAX_IMAGE_NUMBER', 1000))
        # 使用列表实现环形数组存储图片数据
        self.images_array = [None] * self.max_images
        # 文件名到数组索引的映射
        self.filename_to_index = {}
        # 当前指针位置，指向下一个要写入的位置
        self.current_index = 0
        # 已存储的图片数量
        self.count = 0
    
    def save_image(self, mime_type: str, base64_data: str) -> str:
        """将Base64编码的图片保存到内存中的环形数组
        
        Args:
            mime_type: 图片的MIME类型
            base64_data: Base64编码的图片数据
            
        Returns:
            str: 图片的HTTP访问地址
        """
        logger.info(f"保存图片到内存中，当前数量: {self.current_index+1}/{self.max_images}")
        
        # 生成唯一文件名
        file_ext = mime_type.split('/')[-1]
        unique_filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{str(uuid.uuid4())[:8]}.{file_ext}"
        
        # 如果当前位置已有图片，需要从映射中移除旧文件名
        if self.images_array[self.current_index] is not None:
            old_filename = self.images_array[self.current_index]['filename']
            if old_filename in self.filename_to_index:
                del self.filename_to_index[old_filename]
                logger.info(f"覆盖旧图片: {old_filename}")
        
        # 存储到环形数组中
        self.images_array[self.current_index] = {
            'filename': unique_filename,
            'data': base64_data,
            'mime_type': mime_type,
            'created_at': datetime.now()
        }
        
        # 更新文件名到索引的映射
        self.filename_to_index[unique_filename] = self.current_index
        
        # 更新指针位置，实现环形覆盖
        self.current_index = (self.current_index + 1) % self.max_images
        # 更新计数
        if self.count < self.max_images:
            self.count += 1
            
        # 返回HTTP访问地址
        return f"{self.host_url}/memory-images/{unique_filename}"
    
    def get_image(self, filename: str):
        """从内存环形数组中获取图片数据
        
        Args:
            filename: 图片文件名
            
        Returns:
            tuple: (图片数据, MIME类型) 或 None（如果图片不存在）
        """
        if filename in self.filename_to_index:
            index = self.filename_to_index[filename]
            image_info = self.images_array[index]
            return image_info['data'], image_info['mime_type']
        return None, None

    def list_images(self, page: int, page_size: int) -> dict:
        """列出内存中存储的图片，支持分页"""
        # 过滤掉None的值并转换为列表
        all_images = [img for img in self.images_array if img is not None]
        
        # 按创建时间降序排序
        all_images.sort(key=lambda x: x['created_at'], reverse=True)
        
        # 分页
        start = (page - 1) * page_size
        end = start + page_size
        paginated_images_info = all_images[start:end]

        # 构建返回结果
        images_data = [{
            "filename": img['filename'],
            "url": f"{self.host_url}/memory-images/{img['filename']}",
            "created_at": img['created_at'].isoformat()
        } for img in paginated_images_info]

        return {
            "images": images_data,
            "total": len(all_images),
            "page": page,
            "page_size": page_size
        }

    def delete_image(self, filename: str) -> bool:
        """从内存中删除指定的图片"""
        if filename in self.filename_to_index:
            index = self.filename_to_index[filename]
            
            # 从环形数组和映射中删除
            del self.filename_to_index[filename]
            self.images_array[index] = None
            self.count -= 1
            
            logger.info(f"成功从内存中删除图片: {filename}")
            return True
        logger.warning(f"尝试从内存删除但文件不存在: {filename}")
        return False


class TencentCloudImageStorage(ImageStorage):
    """将图片保存到腾讯云COS存储服务"""
    
    def __init__(self, credentials: dict):
        """初始化腾讯云COS存储
        Args:
            credentials: 云服务认证信息,包含secret_id、secret_key、region、bucket和domain
        """
        self.credentials = credentials
        self.secret_id = credentials.get('secret_id')
        self.secret_key = credentials.get('secret_key')
        self.region = credentials.get('region')
        self.bucket = credentials.get('bucket')
        self.domain = credentials.get('domain')
        
        # 初始化腾讯云COS客户端
        config = CosConfig(
            Region=self.region,
            SecretId=self.secret_id,
            SecretKey=self.secret_key,
            Token=None,  # 使用永久密钥时Token为None
            Scheme='https'  # 指定使用https协议
        )
        self.client = CosS3Client(config)        
    
    def save_image(self, mime_type: str, base64_data: str) -> str:
        """将Base64编码的图片保存到腾讯云COS存储
        Args:
            mime_type: 图片的MIME类型
            base64_data: Base64编码的图片数据
        Returns:
            str: 图片的HTTP访问地址
        """
        logger.info(f"保存图片到腾讯云COS存储")
        
        # 生成唯一文件名
        file_ext = mime_type.split('/')[-1]
        unique_filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{str(uuid.uuid4())[:8]}.{file_ext}"
        
        # 解码图片数据
        image_data = base64.b64decode(base64_data)
        
        try:
            # 上传文件到腾讯云COS
            response = self.client.put_object(
                Bucket=self.bucket,
                Body=io.BytesIO(image_data),
                Key=unique_filename,
                ContentType=mime_type
            )
            
            # 返回文件的可访问URL
            return f"{self.domain}/{unique_filename}"
        except Exception as e:
            logger.error(f"上传失败: {e}")
            raise Exception("上传图片到腾讯云COS失败,请检查配置信息")


# 工厂函数，根据配置创建合适的存储实例
def get_image_storage(storage_type: Optional[str] = None) -> ImageStorage:
    """根据环境变量配置或传入的参数创建并返回适当的图片存储实例"""
    if storage_type is None:
        storage_type = os.environ.get('IMAGE_STORAGE_TYPE', 'local').lower()
    else:
        storage_type = storage_type.lower()
    host_url = os.environ.get('HOST_URL', "http://127.0.0.1:7860")
    
    if storage_type == 'local':
        # 使用本地存储
        custom_dir = os.environ.get('IMAGE_STORAGE_DIR')
        return LocalImageStorage(host_url, custom_dir)
        
    elif storage_type == 'memory':
        # 使用内存存储
        return MemoryImageStorage(host_url)
    
    elif storage_type == 'qiniu':
        # 七牛云认证配置信息
        credentials = {
            'access_key': os.environ.get('QINIU_ACCESS_KEY'),
            'secret_key': os.environ.get('QINIU_SECRET_KEY'),
            'bucket_name': os.environ.get('QINIU_BUCKET_NAME'),
            'bucket_domain': os.environ.get('QINIU_BUCKET_DOMAIN')
        }
        return QiniuImageStorage(credentials)
    
    elif storage_type == 'tencent':
        # 腾讯云COS认证配置信息
        credentials = {
            'secret_id': os.environ.get('TENCENT_SECRET_ID'),
            'secret_key': os.environ.get('TENCENT_SECRET_KEY'),
            'region': os.environ.get('TENCENT_REGION'),
            'bucket': os.environ.get('TENCENT_BUCKET'),
            'domain': os.environ.get('TENCENT_DOMAIN')
        }
        return TencentCloudImageStorage(credentials)
    
    else:
        # 默认使用本地存储
        logger.warning(f"未知的存储类型: {storage_type}，使用本地存储作为默认值")
        return LocalImageStorage(host_url)