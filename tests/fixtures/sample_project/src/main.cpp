#include "core/alg.hpp"
#include "core/math.hpp"
#include <string>

int main() {
    (void)core::compute();
    return static_cast<int>(std::string{"ok"}.size() == 2);
}
