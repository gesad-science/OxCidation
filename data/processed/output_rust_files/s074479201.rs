use std::io::{self, BufRead}; 

// Function to calculate Greatest Common Divisor (GCD) using Euclidean algorithm.
fn gcd(a: i64, b: i64) -> i64 {
    let mut a = a.abs();
    let mut b = b.abs();
    while b != 0 {
        let r = a % b;
        a = b;
        b = r;
    }
    a
}

// Function to calculate Least Common Multiple (LCM).
fn lcm(a: i64, b: i64) -> i64 {
    if a == 0 || b == 0 {
        return 0;
    }
    let g = gcd(a, b);
    // Calculate LCM using the formula: |A * B| / GCD(A, B).
    // We divide first to prevent potential i64 overflow.
    (a.abs() / g) * b.abs()
}

// Swaps *x and *y only if *x < *y. (Unused but kept for completeness)
fn swap(x: &mut i64, y: &mut i64) {
    if *x < *y {
        let temp = *x;
        *x = *y;
        *y = temp;
    }
}

fn main() {
    // Use stdin and BufReader to handle input line by line.
    let stdin = io::stdin();
    let mut lines = stdin.lock().lines();

    while let Some(Ok(line)) = lines.next() {
        let trimmed_line = line.trim();
        if trimmed_line.is_empty() {
            continue;
        }

        // Split the line and attempt to parse two i64 values.
        let parts: Vec<&str> = trimmed_line.split_whitespace().collect();

        if parts.len() < 2 {
            continue; // Skip lines that don't contain enough arguments
        }

        // Attempt to parse the first argument (A). If parsing fails, skip line.
        let a = match parts[0].parse::<i64>() {
            Ok(val) => val,
            Err(_) => continue, 
        };

        // Attempt to parse the second argument (B). If parsing fails, skip line.
        let b = match parts[1].parse::<i64>() {
            Ok(val) => val,
            Err(_) => continue,
        };

        // Calculate and print the LCM of A and B.
        println!("{}", lcm(a, b));
    }
}