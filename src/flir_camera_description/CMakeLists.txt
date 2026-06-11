cmake_minimum_required(VERSION 3.16)
project(flir_camera_description)

# find dependencies
find_package(ament_cmake REQUIRED)

install(
  DIRECTORY launch meshes urdf
  DESTINATION share/${PROJECT_NAME}
)

# lint-only tests below; skipped so the build works without the ament lint packages
set(BUILD_TESTING OFF)
if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  ament_lint_auto_find_test_dependencies()
endif()

ament_package()
