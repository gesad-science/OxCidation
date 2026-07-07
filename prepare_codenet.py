import os
import shutil
import glob

base_data_dir = "Project_CodeNet_sample_first_20/data"
base_derived_dir = "Project_CodeNet_sample_first_20/derived/input_output/data"

input_c_dir = "input_c_files"
tests_dir = "tests"

os.makedirs(input_c_dir, exist_ok=True)
os.makedirs(tests_dir, exist_ok=True)

# Iterate over pXXXXXX directories
for p_dir in os.listdir(base_data_dir):
    c_dir_path = os.path.join(base_data_dir, p_dir, "C")
    if not os.path.exists(c_dir_path):
        continue
        
    c_files = glob.glob(os.path.join(c_dir_path, "*.c"))
    if not c_files:
        continue
        
    c_file_path = c_files[0]
    c_file_name = os.path.basename(c_file_path)
    c_file_base = c_file_name.replace(".c", "")
    
    # Check if tests exist
    input_test_path = os.path.join(base_derived_dir, p_dir, "input.txt")
    output_test_path = os.path.join(base_derived_dir, p_dir, "output.txt")
    
    if os.path.exists(input_test_path) and os.path.exists(output_test_path):
        # Copy C file
        dest_c_path = os.path.join(input_c_dir, c_file_name)
        shutil.copy(c_file_path, dest_c_path)
        print(f"Copied {c_file_name}")
        
        # Setup test dir
        test_case_dir = os.path.join(tests_dir, c_file_base)
        os.makedirs(test_case_dir, exist_ok=True)
        
        # Copy tests
        shutil.copy(input_test_path, os.path.join(test_case_dir, "1.in"))
        shutil.copy(output_test_path, os.path.join(test_case_dir, "1.out"))
        print(f"Set up tests for {c_file_base}")

print("Done preparing CodeNet samples.")
