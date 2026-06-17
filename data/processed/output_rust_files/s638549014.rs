use std::io::{self, Write};

fn main() -> io::Result<()> {
    let mut input = String::new();
    // Read the single integer N from standard input
    io::stdin().read_line(&mut input)?;

    // Parse N. Assuming valid input as per C code structure.
    let n: i32 = match input.trim().parse() {
        Ok(num) => num,
        Err(_) => return Ok(()), // Handle parsing error gracefully if needed, though the C code assumes success
    };

    // k corresponds to unsigned long long in C (u64 in Rust)
    let mut k: u64 = 1;

    // Loop from n down to 1 (inclusive). The range syntax is [start, end].
    for i in (1..=n).rev() {
        // We must cast i back to a type compatible with u64 multiplication.
        // Since n was read as i32, and we are multiplying into u64, this conversion is safe 
        // provided n itself fits within the range of u64 (which it does if it's positive).
        k *= i as u64;
    }

    // Print the result.
    println!("{}", k);

    Ok(())
}