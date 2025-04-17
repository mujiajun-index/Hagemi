import os
import base64
import uuid
from datetime import datetime
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
        return f"{self.host_url}/images/{unique_filename}"

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
    """将图片保存到内存中"""
    
    def __init__(self, host_url: str):
        """初始化内存存储
        
        Args:
            host_url: 主机URL，用于构建图片访问地址
        """
        self.host_url = host_url
        # 使用字典存储图片数据
        self.images = {}
    
    def save_image(self, mime_type: str, base64_data: str) -> str:
        """将Base64编码的图片保存到内存中
        
        Args:
            mime_type: 图片的MIME类型
            base64_data: Base64编码的图片数据
            
        Returns:
            str: 图片的HTTP访问地址
        """
        logger.info(f"保存图片到内存")
        
        # 生成唯一文件名
        file_ext = mime_type.split('/')[-1]
        unique_filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{str(uuid.uuid4())[:8]}.{file_ext}"
        
        # 存储到内存字典中
        self.images[unique_filename] = {
            'data': base64_data,
            'mime_type': mime_type,
            'created_at': datetime.now()
        }
        
        # 返回HTTP访问地址
        return f"{self.host_url}/memory-images/{unique_filename}"
    
    def get_image(self, filename: str):
        """从内存中获取图片数据
        
        Args:
            filename: 图片文件名
            
        Returns:
            tuple: (图片数据, MIME类型) 或 None（如果图片不存在）
        """
        if filename in self.images:
            image_info = self.images[filename]
            return image_info['data'], image_info['mime_type']
        return None, None


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
def get_image_storage() -> ImageStorage:
    """根据环境变量配置创建并返回适当的图片存储实例"""
    storage_type = os.environ.get('IMAGE_STORAGE_TYPE', 'memory').lower()
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