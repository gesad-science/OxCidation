use std::io::{self, BufReader, BufRead};

fn main() -> io::Result<()> {
    // Use BufReader for efficient reading of text input
    let stdin = io::stdin();
    let mut reader = BufReader::new(stdin.lock());
    
    // We use a loop that attempts to read all 8 values (x0, y0, x1, y1, x2, y2, xp, yp).
    loop {
        let mut buffer: [f64; 8] = [0.0; 8];
        // tokens_read is unused in the original logic flow after reading the line, but we keep it for structure integrity if needed later.
        // let mut tokens_read = 0; 

        // Read a line of input (assuming space-separated values)
        let mut line = String::new();
        match reader.read_line(&mut line) {
            Ok(0) => break, // EOF reached
            Ok(_) => {
                // Parse all whitespace-separated tokens into f64
                let tokens: Vec<f64> = line
                    .split_whitespace()
                    .filter_map(|s| s.parse::<f64>().ok())
                    .collect();

                if tokens.len() < 8 {
                    // If we read less than 8 values, and it wasn't EOF (which was handled above), 
                    // assume input failure or end of test cases.
                    break;
                }

                // Populate the buffer with the first 8 tokens
                buffer.copy_from_slice(&tokens[0..8]);
            },
            Err(e) => {
                eprintln!("Error reading input: {}", e);
                return Err(e);
            }
        }

        // --- Variable assignment based on buffer contents ---
        let x = [buffer[0], buffer[2], buffer[4]];
        let y = [buffer[1], buffer[3], buffer[5]];
        let mut cp: [f64; 3] = [0.0; 3];
        let xp = buffer[6];
        let yp = buffer[7];

        // The core logic remains identical to C:
        for i in 0..3 { 
            let j = (i + 1) % 3;
            // cp[i] calculation uses the current iteration's x, y, xp, yp values.
            cp[i] = (x[j] - x[i]) * (yp - y[i]) - (y[j] - y[i]) * (xp - x[i]);
        }

        // Check the sign condition:
        if cp[0] > 0.0 && cp[1] > 0.0 && cp[2] > 0.0 || 
           cp[0] < 0.0 && cp[1] < 0.0 && cp[2] < 0.0 {
            println!("YES");
        } else {
            println!("NO");
        }
    }

    Ok(())
}