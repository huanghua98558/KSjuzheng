"""快手 GraphQL 标准 query 字符串.

所有 query 已在 POC 阶段实测通过(2026-04-26),返回 result=1 + 完整数据.

字段说明:
  - Photo (union): 必须 inline fragment ... on PhotoEntity { ... }
  - VisionVideoDetailPhoto (普通 type): 直接 { field } 无 fragment
  - userId 必须用 short uid (`3xxxxx`), 不是 numeric
"""

# ============================================================
# visionProfile - 用户档案 (粉丝数 / 作品数 / 关注数 / 头像 / 性别)
# ============================================================
VISION_PROFILE = """
query visionProfile($userId: String) {
    visionProfile(userId: $userId) {
        result
        hostName
        userProfile {
            ownerCount { fan photo follow photo_public }
            profile {
                gender
                user_name
                user_id
                headurl
                user_text
                user_profile_bg_url
            }
            isFollowing
        }
    }
}
""".strip()


# ============================================================
# visionSearchPhoto - 关键词搜剧 (短剧采集核心)
# ============================================================
VISION_SEARCH_PHOTO = """
query visionSearchPhoto($keyword: String, $pcursor: String, $searchSessionId: String) {
    visionSearchPhoto(keyword: $keyword, pcursor: $pcursor, searchSessionId: $searchSessionId) {
        result
        llsid
        pcursor
        searchSessionId
        feeds {
            type
            author { id name headerUrl }
            photo {
                ... on PhotoEntity {
                    id
                    duration
                    caption
                    likeCount
                    realLikeCount
                    viewCount
                    timestamp
                    coverUrl
                    photoUrl
                }
            }
            tags { type name }
        }
    }
}
""".strip()


# ============================================================
# visionVideoDetail - 单作品详情 (短链解析后用)
# ============================================================
VISION_VIDEO_DETAIL = """
query visionVideoDetail($photoId: String, $page: String) {
    visionVideoDetail(photoId: $photoId, page: $page) {
        status
        type
        llsid
        author { id name headerUrl }
        photo {
            id
            caption
            viewCount
            likeCount
            realLikeCount
            timestamp
            duration
            coverUrl
            photoUrl
            expTag
            llsid
        }
        tags { type name }
    }
}
""".strip()


# ============================================================
# Result Code 翻译表 (visionProfile / visionSearchPhoto)
# ============================================================
RESULT_CODE = {
    1: ("ok", "成功"),
    2: ("no_data", "无数据 / 隐私限制"),
    10: ("user_not_found", "用户不存在或已注销"),
    21: ("bad_uid_format", "uid 格式错(short vs numeric 用错)"),
    109: ("cookie_expired", "Cookie 已过期"),
    116: ("cookie_expired", "Cookie 已过期"),
    400: ("graphql_validation", "GraphQL schema 校验失败"),
    500002: ("risk_blocked", "风控拦截(此码不应出现在主域)"),
}


# ============================================================
# VideoDetail status 翻译表
# ============================================================
VIDEO_STATUS = {
    1: ("ok", "正常"),
    2: ("deleted", "作品已删除"),
    3: ("private", "私密作品"),
    4: ("blocked", "作品被屏蔽"),
}
