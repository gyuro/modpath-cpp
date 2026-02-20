#pragma once

#include <vector>
#include "common/config.h"

namespace core {
inline int add(int a, int b) { return a + b + sample::kConfigVersion - 1; }
inline int sum(const std::vector<int>& values) {
    int out = 0;
    for (int v : values) out += v;
    return out;
}
}
