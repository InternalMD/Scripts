function t() (
    cd build
    cmake --build . --config Debug
    ctest -C Debug --verbose
)
