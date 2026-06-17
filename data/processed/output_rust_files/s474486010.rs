use std::io::{self, Write};

fn main() {
    // Initialize railroad array of size 10 (matching C code)
    let mut railroad: [i32; 10] = [0; 10];
    let mut car: i32;
    let mut i: i32 = 0;

    // Loop to read tokens from standard input until EOF or parsing error.
    loop {
        let mut buffer = String::new();
        
        match io::stdin().read_line(&mut buffer) {
            Ok(0) => break, // EOF reached (no bytes read)
            Ok(_) => {
                // Trim whitespace and attempt to parse the integer.
                let trimmed = buffer.trim();
                if trimmed.is_empty() {
                    continue; 
                }

                match trimmed.parse::<i32>() {
                    Ok(num) => {
                        car = num;
                        // Process the car value immediately after successful parsing
                        if car == 0 { // Leaving
                            i -= 1;
                            // Check bounds before accessing the array (safety measure)
                            if i >= -1 && i < 10 {
                                println!("{}", railroad[i as usize]);
                            }
                        } else { // Entering
                            // Check bounds before writing to the array
                            if i < 10 { 
                                railroad[i as usize] = car;
                                i += 1;
                            } else {
                                // Overflow: Railroad is full. Stop processing input.
                                break; 
                            }
                        }
                    },
                    Err(_) => {
                        // Parsing failed (e.g., non-integer input). Assume end of valid sequence.
                        break;
                    }
                }
            },
            Err(e) => {
                // Handle IO Error
                eprintln!("IO Error: {}", e);
                break;
            }
        }
    }
}