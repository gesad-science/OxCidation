use std::io::{self, Read};

fn main() -> io::Result<()> {
    // We use a buffer to read all tokens from stdin because replicating scanf's 
    // delimited reading until EOF is complex.
    let mut buffer = String::new();
    // FIX: Use the imported Read trait method
    io::stdin().read_to_string(&mut buffer)?; // Read entire standard input into the buffer

    // Split the buffer by whitespace and iterate over tokens. 
    // This mimics scanf's behavior of reading space-separated values.
    let mut tokens = buffer.split_whitespace();

    // We need to process pairs (a, b) until we run out of tokens.
    while let Some(token_a) = tokens.next() {
        let a: i32 = match token_a.parse() {
            Ok(val) => val,
            Err(_) => break, // Stop if parsing fails
        };

        // Check if there is a second token (b)
        if let Some(token_b) = tokens.next() {
            let b: i32 = match token_b.parse() {
                Ok(val) => val,
                Err(_) => break, // Stop if parsing fails
            };

            // Calculate sum n = a + b;
            let mut n = a + b;
            
            // Initialize digit counter
            let mut dig: i32 = 0;

            // Digit counting loop (must replicate the exact logic)
            if n != 0 {
                let mut temp_n = n.abs(); // Use absolute value to count digits correctly regardless of sign
                while temp_n > 0 {
                    temp_n /= 10;
                    dig += 1;
                }
            } else { 
                // If n=0, the C code's loop (while(n!=0)) does not run, leaving dig = 0.
                // We must replicate this behavior exactly.
                dig = 0;
            }

            // Print the result
            println!("{}", dig);
        } else {
            // If we read 'a' but no 'b', break (EOF condition reached)
            break;
        }
    }

    Ok(())
}