from functions.get_files_info import get_files_info
from functions.get_file_content import get_file_content
from functions.write_file import write_file

def main():
    working_dir = "calculator"
    # commented out - 1
    # root_contents = get_files_info(working_dir)
    # print(root_contents)
    # pkg_contents = get_files_info(working_dir, "pkg")
    # print(pkg_contents)
    # pkg_contents = get_files_info(working_dir, "/bin")
    # print(pkg_contents)
    # pkg_contents = get_files_info(working_dir, "../")
    # print(pkg_contents)

    # commented out - 2
    # print(get_file_content(working_dir, "lorem.txt"))
    # print(get_file_content(working_dir, "main.py"))
    # print(get_file_content(working_dir, "pkg/calculator.py"))
    # print(get_file_content(working_dir, "/bin/cat"))
    # print(get_file_content(working_dir, "/pkg/does_not_exist.py"))

    # Currently fresh
    # print(write_file(working_dir, "lorem.txt", "Yep, AI agent just coded over the whole dog on file!"))
    print(write_file("calculator", "pkg/test/morelorem.txt", "had to get em"))
    # print(write_file("calculator", "/tmp/temp.txt", "this should not be allowed"))

main()
