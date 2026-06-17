use std::io::{self, Write}; // Import io for input/output operations

// Function equivalent to void swapc(int *x, int *c)
// Swaps the values pointed to by x and c only if *x > *c.
fn swapc(x: &mut i32, c: &mut i32) {
    if *x > *c {
        let temp = *x;
        *x = *c;
        *c = temp;
    }
}

fn main() -> io::Result<()> {
    // Read N (the number of test cases)
    let mut n_str = String::new();
    io::stdin().read_line(&mut n_str)?; 
    let n: i32 = n_str.trim().parse().expect("Failed to parse N");

    // Loop N times
    for _ in 0..n {
        // Read a, b, c for the current test case
        let mut line = String::new();
        io::stdin().read_line(&mut line)?; 
        let parts: Vec<i32> = line.trim()
            .split_whitespace()
            .map(|s| s.parse().expect("Failed to parse integer"))
            .collect();

        if parts.len() != 3 {
            // Handle malformed input if necessary, though assuming valid input based on C code structure
            continue;
        }

        // Initialize local variables a, b, c (these will hold the values read from stdin)
        let mut a = parts[0];
        let mut b = parts[1];
        let mut c = parts[2];

        // The C code passes addresses (&a, &c) and modifies the variables in place.
        // In Rust, we pass mutable references to these local variables.
        swapc(&mut a, &mut c);
        swapc(&mut b, &mut c);

        // Check if a*a + b*b == c*c. 
        // We cast to i64 before multiplication and addition to prevent potential integer overflow,
        // as the squares of i32 values might exceed i32 limits.
        let lhs: i64 = (a as i64) * (a as i64) + (b as i64) * (b as i64);
        let rhs: i64 = (c as i64) * (c as i64);

        if lhs == rhs {
            println!("YES\n");
        } else {
            println!("NO\n");
        }
    }

    Ok(())
}