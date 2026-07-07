use std::io::{self, Write};

fn main() {
    // We use a vector of size 11 to mimic the C array n[10] while allowing index 0 to be unused,
    // thus supporting indices 1 through 10 as per the original logic.
    let mut n: Vec<i32> = vec![0; 11];

    // --- Input Reading (Mimicking scanf loop) ---
    // Read 10 integers into n[1] through n[10]
    for k in 1..=10 {
        let mut input = String::new();
        
        // Removed interactive prompts to ensure compatibility with automated test environments.
        match io::stdin().read_line(&mut input) {
            Ok(_) => { 
                // Trim whitespace and parse the number
                if let Ok(a) = input.trim().parse::<i32>() {
                    n[k] = a;
                } else {
                    eprintln!("Failed to parse integer for n[{}]. Using 0.", k);
                    n[k] = 0;
                }
            },
            Err(e) => {
                // If reading fails (e.g., EOF reached unexpectedly), we stop processing.
                if e.kind() != io::ErrorKind::UnexpectedEof {
                     eprintln!("Error reading input: {}", e);
                }
                break; 
            }
        }
    }

    // --- Sorting Logic (Bubble Sort implementation, matching C structure) ---
    // This specific logic sorts the array segment n[1..=10] in descending order.
    for i in 1..=10 {
        let mut j = 10;
        while j >= i + 1 { 
            if n[j] > n[j - 1] { 
                // Swap n[j-1] and n[j] (Moves larger element left)
                let tmp = n[j - 1];
                n[j - 1] = n[j];
                n[j] = tmp;
            }
            j -= 1;
        }
    }

    // --- Output (Print n[1], n[2], n[3]) ---
    println!("{}", n[1]);
    println!("{}", n[2]);
    println!("{}", n[3]);
}