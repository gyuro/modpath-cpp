#pragma once

#include "core/math.hpp"
#include "core/cycle_a.hpp"

namespace core {
inline int compute() {
    std::vector<int> values{1, 2, 3};
    return sum(values);
}
}
