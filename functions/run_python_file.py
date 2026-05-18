# import os
# import subprocess
#
#
# def run_python_file(working_directory: str, file_path: str, args=None):
#     abs_working_dir = os.path.abspath(working_directory)
#     abs_file_path = os.path.abspath(os.path.join(working_directory, file_path))
#
#     if not abs_file_path.startswith(abs_working_dir):
#         return f'Error: *{file_path}* is not in the working directory'
#     if not os.path.isfile(abs_file_path):
#         return f'Error: Cannot read "{file_path}" as it is outside the permitted working directory'
#     if not file_path.endswith('.py'):
#         return f'Error: "{file_path}" is not a Python file.'
#     command = ["python", abs_file_path]
#     if args:
#         command.extend(args)
#     result = subprocess.run(
#         command,
#         cwd=abs_working_dir,
#         capture_output=True,
#         text=True,
#         timeout=30,
#     )
#     try:
#         output = subprocess.run(["python3", abs_file_path],
#                                 cwd=abs_working_dir, timeout=30, capture_output=True)
#         final_string = f"""
# STDOUT: {output.stdout.decode()}
# STDERR: {output.stderr.decode()}
# """
#         if output.stdout == b"" and output.stderr == b"":
#             final_string += "No output produced.\n"
#
#         if output.returncode != 0:
#             final_string += f"Process exited with code {output.returncode}"
#
#         return final_string
#     except Exception as e:
#         return f"Error: executing Python file: {e}"
#
#
import os
import subprocess


def run_python_file(working_directory, file_path, args=None):
    try:
        abs_working_dir = os.path.abspath(working_directory)
        abs_file_path = os.path.normpath(os.path.join(abs_working_dir, file_path))
        if os.path.commonpath([abs_working_dir, abs_file_path]) != abs_working_dir:
            return f'Error: Cannot execute "{file_path}" as it is outside the permitted working directory'
        if not os.path.isfile(abs_file_path):
            return f'Error: "{file_path}" does not exist or is not a regular file'
        if not abs_file_path.endswith(".py"):
            return f'Error: "{file_path}" is not a Python file'
        command = ["python", abs_file_path]
        if args:
            command.extend(args)
        result = subprocess.run(
            command,
            cwd=abs_working_dir,
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = []
        if result.returncode != 0:
            output.append(f"Process exited with code {result.returncode}")
        if not result.stdout and not result.stderr:
            output.append("No output produced")
        if result.stdout:
            output.append(f"STDOUT:\n{result.stdout}")
        if result.stderr:
            output.append(f"STDERR:\n{result.stderr}")
        return "\n".join(output)
    except Exception as e:
        return f"Error: executing Python file: {e}"
