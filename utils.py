import json
from pathlib import Path

import yaml
from loguru import logger


def convert_yaml_to_json(yaml_path: str, json_path: str) -> None:
    """
    config.yaml 파일을 config.json 형식으로 변환합니다.
    설정은 global -> groups -> users 순서로 상속되며,
    하위 레벨에서 정의된 설정이 상위 레벨의 설정을 덮어씁니다.

    Args:
        yaml_path (str): YAML 파일 경로
        json_path (str): 출력할 JSON 파일 경로

    Raises:
        ValueError: 동일한 platform:id 쌍을 가진 중복 사용자가 발견된 경우
    """
    try:
        # YAML 파일 읽기
        with open(yaml_path, "r", encoding="utf-8") as f:
            yaml_data = yaml.safe_load(f)

        # 전역 설정 추출 (groups를 제외한 모든 설정)
        global_config = {k: v for k, v in yaml_data.items() if k != "groups"}

        # JSON 형식으로 변환
        json_data = {"proxy": global_config.get("proxy"), "output": global_config.get("output"), "user": []}

        # 전역 설정에서 기본 키를 제외한 나머지 설정들 추가
        for key, value in global_config.items():
            if key not in ["proxy", "output"]:
                json_data[key] = value

        # 중복 체크를 위한 사용자 집합과 위치 추적
        processed_users = {}

        # groups 처리
        for group_idx, group in enumerate(yaml_data.get("groups", []), 1):
            platform = group.get("platform")

            # 그룹 설정 (platform과 users를 제외한 모든 설정)
            group_config = {k: v for k, v in group.items() if k not in ["platform", "users"]}

            # 각 사용자에 대해 설정 생성
            for user_idx, user in enumerate(group.get("users", []), 1):
                user_id = user.get("id")
                user_key = (platform, user_id)

                # 중복 사용자 체크
                if user_key in processed_users:
                    prev_location = processed_users[user_key]
                    current_location = f"groups[{group_idx}].users[{user_idx}]"
                    error_msg = f"중복된 사용자 발견: platform='{platform}', id='{user_id}'\n" f"첫 번째 위치: {prev_location}\n" f"중복된 위치: {current_location}"
                    logger.error(error_msg)
                    raise ValueError(error_msg)

                # 사용자 위치 기록
                processed_users[user_key] = f"groups[{group_idx}].users[{user_idx}]"

                # 기본 사용자 설정
                user_config = {"platform": platform, "id": user_id, "name": user.get("name", user_id)}

                # 사용자 개별 설정이 그룹이나 전역 설정과 다른 경우에만 추가
                for key, value in user.items():
                    if key not in ["id", "name"]:
                        if key not in group_config or group_config[key] != value:
                            if key not in global_config or global_config[key] != value:
                                user_config[key] = value

                # 그룹 설정이 전역 설정과 다른 경우에만 추가
                for key, value in group_config.items():
                    if key not in user_config:
                        if key not in global_config or global_config[key] != value:
                            user_config[key] = value

                json_data["user"].append(user_config)

        # JSON 파일 쓰기
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(json_data, f, indent=2, ensure_ascii=False)

        logger.info(f"YAML을 JSON으로 변환 완료: {yaml_path} -> {json_path}")

    except Exception as e:
        logger.error(f"YAML -> JSON 변환 중 오류 발생: {str(e)}")
        raise


def is_yaml_changed(yaml_path: str, json_path: str) -> bool:
    """
    YAML 파일이 JSON 파일보다 최신인지 확인합니다.

    Args:
        yaml_path (str): YAML 파일 경로
        json_path (str): JSON 파일 경로

    Returns:
        bool: YAML 파일이 더 최신이면 True
    """
    yaml_file = Path(yaml_path)
    json_file = Path(json_path)

    if not json_file.exists():
        return True

    return yaml_file.stat().st_mtime > json_file.stat().st_mtime


if __name__ == "__main__":
    # 로거 설정
    logger.add(
        sink="logs/log_{time:YYYY-MM-DD}.log", rotation="00:00", retention="3 days", level="INFO", encoding="utf-8", format="[{time:YYYY-MM-DD HH:mm:ss}][{level}][{name}][{function}:{line}]{message}"
    )

    try:
        # YAML -> JSON 변환 테스트
        yaml_path = "test_config.yaml"
        json_path = "test_config.json"

        if not Path(yaml_path).exists():
            logger.error(f"{yaml_path} 파일이 존재하지 않습니다.")
            exit(1)

        logger.info(f"YAML -> JSON 변환 테스트 시작: {yaml_path} -> {json_path}")
        convert_yaml_to_json(yaml_path, json_path)
        logger.info("변환 테스트 완료")

    except Exception as e:
        logger.error(f"테스트 중 오류 발생: {str(e)}")
        raise
