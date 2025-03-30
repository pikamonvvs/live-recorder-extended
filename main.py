import asyncio
import json
import sys
from pathlib import Path
from typing import Dict, Set

# live-recorder 폴더를 Python 경로에 추가
sys.path.append("live-recorder")

from live_recorder import recording  # recording 딕셔너리 import 추가
from live_recorder import (  # live_recorder.py에서 직접 import
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
)
from loguru import logger
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

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
running_instances: Dict[tuple, asyncio.Task] = {}  # 문자열 대신 튜플을 키로 사용
processed_configs: Set[tuple] = set()


class ConfigFileHandler(FileSystemEventHandler):
    def __init__(self, loop):
        self.loop = loop
        super().__init__()

    def on_modified(self, event):
        if event.src_path.endswith("config.json"):
            logger.info(f"config.json 파일 변경 감지: {event.src_path}")
            asyncio.run_coroutine_threadsafe(handle_config_changes(), self.loop)


async def create_recorder_instance(config: dict, item: dict) -> asyncio.Task:
    platform = item["platform"]
    if platform not in PLATFORM_CLASSES:
        raise ValueError(f"지원하지 않는 플랫폼입니다: {platform}")

    platform_class = PLATFORM_CLASSES[platform]
    instance = platform_class(config, item)
    return asyncio.create_task(instance.start())


async def handle_config_changes():
    try:
        logger.info("설정 변경 처리 시작")
        await asyncio.sleep(0.1)

        try:
            logger.info("config.json 파일 읽기 시도")
            with open("config.json", "r", encoding="utf-8") as f:
                config = json.load(f)
            logger.info("config.json 파일 읽기 성공")
        except FileNotFoundError:
            logger.error("config.json 파일을 찾을 수 없습니다.")
            return
        except json.JSONDecodeError:
            logger.error("config.json 파일이 올바른 JSON 형식이 아닙니다.")
            return
        except Exception as e:
            logger.error(f"config.json 파일을 읽는 중 오류 발생: {e}")
            return

        if not isinstance(config, dict) or "user" not in config:
            logger.error("config.json 파일의 형식이 올바르지 않습니다. 'user' 항목이 필요합니다.")
            return

        # 현재 config에 있는 모든 설정의 키 집합
        current_configs = set()

        # 새로운 설정 처리
        logger.info("새로운 설정 처리 시작")
        for item in config["user"]:
            if not all(key in item for key in ["platform", "id"]):
                logger.error(f"잘못된 설정 항목 발견: {item}. 'platform'과 'id'는 필수 필드입니다.")
                continue

            instance_key = (item["platform"], item["id"])
            current_configs.add(instance_key)

            # 새로운 설정 추가
            if instance_key not in processed_configs:
                logger.info(f"새로운 설정 감지: {item['platform']} - {item['id']}")
                task = await create_recorder_instance(config, item)
                running_instances[instance_key] = task
                processed_configs.add(instance_key)
                logger.info(f"새로운 레코더 인스턴스 생성 완료: {item['platform']} - {item['id']}")

        # 삭제된 설정 처리
        logger.info("삭제된 설정 처리 시작")
        removed_configs = processed_configs - current_configs
        logger.info(f"현재 처리된 설정: {processed_configs}")
        logger.info(f"현재 config의 설정: {current_configs}")
        logger.info(f"삭제할 설정: {removed_configs}")

        for instance_key in list(removed_configs):
            # 이미 processed_configs에서 제거된 경우 건너뛰기
            if instance_key not in processed_configs:
                continue

            logger.info(f"삭제된 설정 감지: {instance_key[0]} - {instance_key[1]}")

            if instance_key in running_instances:
                task = running_instances.pop(instance_key)
                logger.info(f"태스크 취소 시도: {instance_key}")

                # 스트림과 파일 닫기
                platform, user_id = instance_key
                # URL 형식 수정
                if platform == "Afreeca":
                    stream_url = f"https://play.afreecatv.com/{user_id}"
                else:
                    stream_url = f"https://{platform.lower()}.com/{user_id}"

                logger.info(f"스트림 URL 확인: {stream_url}")
                if stream_url in recording:
                    logger.info(f"스트림 종료 시도: {stream_url}")
                    stream_fd, output = recording[stream_url]
                    stream_fd.close()
                    output.close()
                    recording.pop(stream_url, None)
                    logger.info(f"스트림 종료 완료: {stream_url}")
                else:
                    logger.warning(f"스트림을 찾을 수 없음: {stream_url}")
                    logger.info(f"현재 recording 상태: {list(recording.keys())}")

                # 태스크 취소
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=5.0)
                    logger.info(f"태스크 정상 종료: {instance_key}")
                except asyncio.TimeoutError:
                    logger.warning(f"태스크 종료 타임아웃: {instance_key}")
                except asyncio.CancelledError:
                    logger.info(f"태스크 취소 완료: {instance_key}")
                except Exception as e:
                    logger.error(f"태스크 종료 중 오류 발생: {instance_key}: {e}")
                finally:
                    processed_configs.remove(instance_key)
                    logger.info(f"설정 제거 완료: {instance_key}")
            else:
                logger.warning(f"실행 중인 태스크를 찾을 수 없음: {instance_key}")

        logger.info(f"설정 변경 처리 완료. 현재 실행 중인 태스크: {len(running_instances)}")
        logger.info(f"현재 실행 중인 태스크 키: {list(running_instances.keys())}")
        logger.info(f"현재 recording 상태: {list(recording.keys())}")

    except Exception as e:
        logger.error(f"설정 변경 처리 중 오류 발생: {e}")
        logger.exception(e)  # 스택 트레이스 출력


async def modified_run():
    # 초기 설정 로드 및 감시 설정
    logger.info("프로그램 시작")
    config_path = Path("config.json")

    # 현재 이벤트 루프 가져오기
    loop = asyncio.get_running_loop()

    observer = Observer()
    observer.schedule(ConfigFileHandler(loop), str(config_path.parent), recursive=False)
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
    logger.add(
        sink="logs/log_{time:YYYY-MM-DD}.log", rotation="00:00", retention="3 days", level="INFO", encoding="utf-8", format="[{time:YYYY-MM-DD HH:mm:ss}][{level}][{name}][{function}:{line}]{message}"
    )

    try:
        asyncio.run(modified_run())
    except KeyboardInterrupt:
        logger.warning("프로그램이 강제 종료되었습니다.")
