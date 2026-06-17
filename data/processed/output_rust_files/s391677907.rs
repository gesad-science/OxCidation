use std::io::{self, Write}; // Import io for standard input/output operations

fn main() -> io::Result<()> {
    // Use a loop to read integers until EOF is reached.
    loop {
        let mut input = String::new();
        // Read one line of input (which should contain the integer n)
        match io::stdin().read_line(&mut input) { 
            Ok(0) => break, // EOF detected
            Ok(_) => { 
                // Trim whitespace and attempt to parse the integer
                let n: i32 = match input.trim().parse() {
                    Ok(num) => num,
                    Err(_) => continue, // Skip if parsing fails (e.g., empty line)
                };

                let mut count = 0;

                // Nested loops for a, b, c, d from 0 to 9
                for a in 0..10 {
                    for b in 0..10 {
                        for c in 0..10 {
                            for d in 0..10 {
                                // Check the condition: a + b + c + d == n
                                if (a + b + c + d) == n {
                                    count += 1;
                                }
                            }
                        }
                    }
                }

                // Print the result for the current input n
                println!("{}", count);
            },
            Err(e) => { 
                eprintln!("Error reading input: {}", e); // Handle read error
                break;
            }
        }
    }
    Ok(())
}