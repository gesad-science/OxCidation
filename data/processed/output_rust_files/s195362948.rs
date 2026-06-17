use std::io::{self, BufReader, BufRead};

fn main() {
    // n[1000] in C. We use an array of size 6 to accommodate indices 1 through 5.
    let mut n: [i32; 6] = [0; 6];
    
    // Use BufReader for reliable sequential line reading from stdin
    let stdin = io::stdin();
    let mut reader = BufReader::new(stdin.lock());

    // Reading 5 inputs into n[1] through n[5]. We assume input is piped/provided sequentially.
    for i in 1..=5 {
        let mut input = String::new();
        
        // Read the line using the buffered reader
        match reader.read_line(&mut input) {
            Ok(0) => panic!("Failed to read input for element {}", i), // EOF encountered prematurely
            Ok(_) => {},
            Err(e) => panic!("Failed to read line: {}", e),
        }
        
        // Handle potential trailing newline characters when parsing
        let trimmed_input = input.trim();
        if trimmed_input.is_empty() {
             panic!("Input cannot be empty.");
        }

        match trimmed_input.parse::<i32>() {
            Ok(val) => n[i] = val,
            Err(_) => panic!("Invalid integer input.")
        }
    }

    // Output: Print n[1] through n[5] separated by spaces
    let mut output = String::new();
    for i in 1..=5 {
        output.push_str(&n[i].to_string());
        if i < 5 {
            output.push(' ');
        }
    }
    println!("{}", output);
}