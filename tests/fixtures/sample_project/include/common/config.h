#pragma once

#define MP_CFG_VERSION 1
#define MP_CFG_ENABLE_LOG 1
#define MP_CFG_LOG_LEVEL 3
#define MP_CFG_MAX_BATCH 64
#define MP_CFG_MIN_BATCH 4
#define MP_CFG_FAST_PATH 1
#define MP_CFG_SLOW_PATH 0
#define MP_CFG_USE_SIMD 1
#define MP_CFG_TIMEOUT_MS 200
#define MP_CFG_RETRY_COUNT 3

namespace sample {
inline constexpr int kConfigVersion = MP_CFG_VERSION;
}
