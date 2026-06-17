use std::io::{self, Write}; // Import io for standard input/output operations

fn main() {
    // We use a loop that attempts to read integers from stdin until EOF or the explicit break condition (a=0).
    loop {
        let mut input = String::new();
        // Read one line of input. This handles reading tokens separated by whitespace.
        match io::stdin().read_line(&mut input) { 
            Ok(0) => break, // EOF reached (End Of File)
            Ok(_) => {
                let a: i32 = match input.trim().parse() {
                    Ok(num) => num,
                    Err(_) => continue, // Skip if parsing fails
                };

                // --- Start of C logic translation ---
                if a == 0 { 
                    break; // Explicit break condition from C code
                }

                let b = 600 / a;
                let mut sum: i32 = 0;

                // for(i=1; i<b; i++) translates to range (1..b)
                for i in 1..b {
                    // e = i * a;
                    let e = i * a;
                    // d = e * e;
                    let d = e * e;
                    // c = a * d;
                    let c = a * d;
                    
                    sum += c;
                }
                
                println!("{}", sum);
                // --- End of C logic translation ---
            },
            Err(_) => break, // Handle other IO errors (e.g., broken pipe)
        }
    }
}