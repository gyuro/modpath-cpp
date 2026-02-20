#include "core/math.hpp"
#include "common/config.h"
#include <map>

int run_tool() {
    std::map<int, int> m{{1, 2}};
    return core::add(1, static_cast<int>(m.size()));
}
