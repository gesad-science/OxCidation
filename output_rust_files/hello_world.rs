use std::io;

fn main() {
    // The variable 'name' is declared but never used. We can keep it if we assume it was part of a larger context, 
    // but since it serves no purpose here, I will leave it as is to minimize changes while fixing the compilation environment issues.
    let mut name = [0u8; 100];

    // Reading a string from stdin using scanf-like behavior (reading up to 99 characters)
    // In Rust, reading formatted input like C's scanf is usually done with specialized crates or manual handling.
    // Since the original code uses %99s, we read into a fixed-size buffer and assume it's null-terminated/string content.

    let mut input_buffer = String::with_capacity(100);
    if io::stdin().read_line(&mut input_buffer).is_ok() {
        // Trim potential newline characters added by read_line, mimicking scanf's behavior of reading only the word.
        let name_str = input_buffer.trim();
        if !name_str.is_empty() {
            println!("Hello, {}!", name_str);
        }
    }
}