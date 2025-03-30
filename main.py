import asyncio
import json
import sys
from pathlib import Path
from typing import Dict, Set

sys.path.append("live-recorder")

from live_recorder import (
    Afreeca,
    Bigolive,
    Bilibili,
    Chaturbate,
    Douyin,
    Douyu,
    Huya,
    Niconico,
    Pandalive,
    Pixivsketch,
    Twitcasting,
    Twitch,
    Youtube,
    recording,
)
from loguru import logger
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from utils import convert_yaml_to_json, is_yaml_changed

# 플랫폼 클래스 매핑
PLATFORM_CLASSES = {
    "Afreeca": Afreeca,
    "Bilibili": Bilibili,
    "Douyu": Douyu,
    "Huya": Huya,
    "Douyin": Douyin,
    "Youtube": Youtube,
    "Twitch": Twitch,
    "Niconico": Niconico,
    "Twitcasting": Twitcasting,
    "Pandalive": Pandalive,
    "Bigolive": Bigolive,
    "Pixivsketch": Pixivsketch,
    "Chaturbate": Chaturbate,
}

# 실행 중인 인스턴스 추적을 위한 전역 변수
running_instances: Dict[tuple, asyncio.Task] = {}
processed_configs: Set[tuple] = set()

# 상수 정의
CONFIG_FILE = "config.json"
LOGS_PATH = "logs/log_{time:YYYY-MM-DD}.log"
LIVE_RECORDER_PATH = "live-recorder"

# URL 포맷
AFREECA_URL_FORMAT = "https://play.afreecatv.com/{}"
DEFAULT_URL_FORMAT = "https://{}.com/{}"

# 필수 설정 키
REQUIRED_CONFIG_KEYS = ["platform", "id"]
USER_CONFIG_KEY = "user"


class ConfigFileHandler(FileSystemEventHandler):
    def __init__(self, loop):
        self.loop = loop
        super().__init__()

    def on_modified(self, event):
        if str(event.src_path).endswith(CONFIG_FILE):
            logger.info(f"{CONFIG_FILE} 파일 변경 감지: {event.src_path}")
            asyncio.run_coroutine_threadsafe(handle_config_changes(), self.loop)
        elif str(event.src_path).endswith("config.yaml"):
            logger.info("config.yaml 파일 변경 감지")
            try:
                convert_yaml_to_json("config.yaml", CONFIG_FILE)
            except Exception as e:
                logger.error(f"YAML 변환 중 오류 발생: {str(e)}")


async def create_recorder_instance(config: dict, item: dict) -> asyncio.Task:
    platform = item["platform"]
    if platform not in PLATFORM_CLASSES:
        raise ValueError(f"지원하지 않는 플랫폼입니다: {platform}")

    platform_class = PLATFORM_CLASSES[platform]
    instance = platform_class(config, item)
    return asyncio.create_task(instance.start())


class ConfigManager:
    @staticmethod
    async def load_config() -> dict:
        """설정 파일을 로드하고 검증합니다."""
        try:
            if not Path(CONFIG_FILE).exists():
                raise FileNotFoundError(f"{CONFIG_FILE} 파일이 존재하지 않습니다.")

            logger.info(f"{CONFIG_FILE} 파일 읽기 시도")
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
            logger.info(f"{CONFIG_FILE} 파일 읽기 성공")

            if not isinstance(config, dict):
                raise ValueError(f"{CONFIG_FILE} 파일이 딕셔너리 형식이 아닙니다.")

            if USER_CONFIG_KEY not in config:
                raise ValueError(f"{CONFIG_FILE} 파일에 '{USER_CONFIG_KEY}' 항목이 없습니다.")

            if not isinstance(config[USER_CONFIG_KEY], list):
                raise ValueError(f"'{USER_CONFIG_KEY}' 항목이 리스트 형식이 아닙니다.")

            return config
        except (FileNotFoundError, json.JSONDecodeError, ValueError) as e:
            logger.error(f"설정 파일 로드 중 오류 발생: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"예상치 못한 오류 발생: {str(e)}")
            raise

    @staticmethod
    def validate_config_item(item: dict) -> tuple:
        """개별 설정 항목을 검증하고 instance_key를 반환합니다."""
        if not isinstance(item, dict):
            raise ValueError("설정 항목이 딕셔너리 형식이 아닙니다.")

        missing_keys = [key for key in REQUIRED_CONFIG_KEYS if key not in item]
        if missing_keys:
            raise ValueError(f"필수 키가 누락되었습니다: {missing_keys}")

        platform = item.get("platform")
        user_id = item.get("id")

        if not isinstance(platform, str) or not platform:
            raise ValueError("platform은 비어있지 않은 문자열이어야 합니다.")

        if not isinstance(user_id, str) or not user_id:
            raise ValueError("id는 비어있지 않은 문자열이어야 합니다.")

        return (platform, user_id)

    @staticmethod
    async def process_new_instance(config: dict, item: dict, instance_key: tuple):
        """새로운 레코더 인스턴스를 생성하고 처리합니다."""
        if not config or not item or not instance_key:
            raise ValueError("필수 매개변수가 None입니다.")

        if len(instance_key) != 2:
            raise ValueError("잘못된 instance_key 형식입니다.")

        if instance_key not in processed_configs:
            platform, user_id = instance_key
            logger.info(f"새로운 설정 감지: {platform} - {user_id}")

            try:
                task = await create_recorder_instance(config, item)
                if task is None:
                    raise ValueError("레코더 인스턴스 생성 실패")

                running_instances[instance_key] = task
                processed_configs.add(instance_key)
                logger.info(f"새로운 레코더 인스턴스 생성 완료: {platform} - {user_id}")
            except Exception as e:
                logger.error(f"인스턴스 생성 중 오류 발생: {str(e)}")
                raise

    @staticmethod
    async def cleanup_removed_instance(instance_key: tuple):
        """제거된 인스턴스를 정리합니다."""
        if not instance_key or len(instance_key) != 2:
            logger.error("잘못된 instance_key 형식")
            return

        if instance_key not in running_instances:
            logger.warning(f"실행 중인 태스크를 찾을 수 없음: {instance_key}")
            return

        try:
            # 태스크 취소를 먼저 수행
            await ConfigManager.cancel_task(instance_key)

            # 스트림 정리는 태스크 취소 후에 수행
            platform, user_id = instance_key
            stream_url = ConfigManager.get_stream_url(platform, user_id)
            if stream_url:
                await ConfigManager.close_stream(stream_url)

        except Exception as e:
            logger.error(f"인스턴스 정리 중 오류 발생: {str(e)}")
            raise

    @staticmethod
    def get_stream_url(platform: str, user_id: str) -> str:
        """스트림 URL을 생성합니다."""
        if not isinstance(platform, str) or not isinstance(user_id, str):
            raise ValueError("platform과 user_id는 문자열이어야 합니다.")

        if not platform or not user_id:
            raise ValueError("platform과 user_id는 비어있지 않아야 합니다.")

        try:
            return AFREECA_URL_FORMAT.format(user_id) if platform == "Afreeca" else DEFAULT_URL_FORMAT.format(platform.lower(), user_id)
        except Exception as e:
            logger.error(f"URL 생성 중 오류 발생: {str(e)}")
            raise

    @staticmethod
    async def close_stream(stream_url: str):
        """스트림과 관련 리소스를 정리합니다."""
        if not stream_url:
            logger.error("스트림 URL이 비어있습니다.")
            return

        if stream_url not in recording:
            logger.warning(f"활성 스트림을 찾을 수 없음: {stream_url}")
            return

        try:
            logger.info(f"스트림 종료 시도: {stream_url}")
            stream_fd, output = recording[stream_url]

            if stream_fd:
                stream_fd.close()
            if output:
                output.close()

            recording.pop(stream_url, None)
            logger.info(f"스트림 종료 완료: {stream_url}")
        except Exception as e:
            logger.error(f"스트림 종료 중 오류 발생: {str(e)}")
            raise

    @staticmethod
    async def cancel_task(instance_key: tuple):
        """실행 중인 태스크를 취소합니다."""
        if instance_key not in running_instances:
            logger.warning(f"취소할 태스크를 찾을 수 없음: {instance_key}")
            return

        try:
            task = running_instances.pop(instance_key)
            if not task:
                raise ValueError("태스크가 None입니다.")

            task.cancel()
            try:
                await asyncio.wait_for(task, timeout=5.0)
                logger.info(f"태스크 정상 종료: {instance_key}")
            except asyncio.TimeoutError:
                logger.warning(f"태스크 종료 타임아웃: {instance_key}")
            except asyncio.CancelledError:
                logger.info(f"태스크 취소 완료: {instance_key}")
            finally:
                if instance_key in processed_configs:
                    processed_configs.remove(instance_key)
        except Exception as e:
            logger.error(f"태스크 취소 중 오류 발생: {str(e)}")
            raise


async def handle_config_changes():
    """설정 변경을 처리하는 메인 함수"""
    try:
        logger.info("설정 변경 처리 시작")
        await asyncio.sleep(0.1)

        config = await ConfigManager.load_config()
        current_configs = set()

        # 새로운 설정 처리
        logger.info("새로운 설정 처리 시작")
        for item in config[USER_CONFIG_KEY]:
            try:
                instance_key = ConfigManager.validate_config_item(item)
                current_configs.add(instance_key)
                await ConfigManager.process_new_instance(config, item, instance_key)
            except Exception as e:
                logger.error(f"설정 항목 처리 중 오류 발생: {item}: {e}")
                logger.exception(e)
                continue

        # 삭제된 설정 처리
        logger.info("삭제된 설정 처리 시작")
        removed_configs = processed_configs - current_configs
        for instance_key in list(removed_configs):
            if instance_key in processed_configs:
                await ConfigManager.cleanup_removed_instance(instance_key)

        logger.info(f"설정 변경 처리 완료. 현재 실행 중인 태스크: {len(running_instances)}")

    except Exception as e:
        logger.error(f"설정 변경 처리 중 오류 발생: {e}")
        logger.exception(e)


async def modified_run():
    # 초기 설정 로드 및 감시 설정
    logger.info("프로그램 시작")

    # YAML -> JSON 초기 변환
    if Path("config.yaml").exists():
        if is_yaml_changed("config.yaml", CONFIG_FILE):
            logger.info("config.yaml 변경 감지됨, JSON으로 변환 중...")
            convert_yaml_to_json("config.yaml", CONFIG_FILE)

    config_dir = Path(CONFIG_FILE).parent

    # 현재 이벤트 루프 가져오기
    loop = asyncio.get_running_loop()

    observer = Observer()
    handler = ConfigFileHandler(loop)
    observer.schedule(handler, str(config_dir), recursive=False)
    observer.start()
    logger.info("파일 감시 시작")

    try:
        # 초기 설정 처리
        logger.info("초기 설정 처리 시작")
        await handle_config_changes()

        # 프로그램이 계속 실행되도록 유지
        logger.info("메인 루프 시작")
        while True:
            await asyncio.sleep(1)

    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        logger.warning("사용자가 프로그램을 중단했습니다. 모든 레코더를 종료합니다.")

        # 모든 스트림과 파일 닫기
        for stream_url, (stream_fd, output) in recording.copy().items():
            logger.info(f"스트림 종료 시도: {stream_url}")
            try:
                stream_fd.close()
                output.close()
                recording.pop(stream_url, None)
                logger.info(f"스트림 종료 완료: {stream_url}")
            except Exception as e:
                logger.error(f"스트림 종료 중 오류 발생: {stream_url}: {e}")

        # 모든 태스크 취소
        for instance_key, task in running_instances.items():
            logger.info(f"태스크 취소 시도: {instance_key}")
            task.cancel()
            try:
                await asyncio.wait_for(task, timeout=5.0)
                logger.info(f"태스크 정상 종료: {instance_key}")
            except Exception as e:
                logger.error(f"태스크 종료 중 오류 발생: {instance_key}: {e}")

        observer.stop()
        observer.join()
        logger.info("프로그램 정상 종료")

        # 남은 태스크들 강제 종료
        for task in asyncio.all_tasks(loop):
            if not task.done() and task != asyncio.current_task():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass


if __name__ == "__main__":
    logger.add(sink=LOGS_PATH, rotation="00:00", retention="3 days", level="INFO", encoding="utf-8", format="[{time:YYYY-MM-DD HH:mm:ss}][{level}][{name}][{function}:{line}]{message}")

    try:
        asyncio.run(modified_run())
    except KeyboardInterrupt:
        logger.warning("프로그램이 강제 종료되었습니다.")
    finally:
        input("프로그램을 종료하려면 Enter 키를 누르세요...")
