use std::io::{self, BufRead};

fn main() -> io::Result<()> {
    let stdin = io::stdin();
    let mut lines = stdin.lock().lines();

    // Initialize variables matching C code types and state
    let mut x: f64 = 0.0;
    let mut y: f64 = 0.0;
    let mut rad: i32 = 90;

    loop {
        let line = match lines.next() {
            Some(Ok(l)) => l,
            Some(Err(_)) => break, // Handle IO error
            None => break,       // EOF reached
        };

        // Parse the input format "d,r"
        let parts: Vec<&str> = line.split(',').collect();
        if parts.len() != 2 {
            continue; // Skip malformed lines
        }

        // Attempt to parse integers
        let d_res = parts[0].trim().parse::<i32>();
        let r_res = parts[1].trim().parse::<i32>();

        if let (Ok(d), Ok(r)) = (d_res, r_res) {
            // Check the break condition: if d=0 and r=0
            if d == 0 && r == 0 { 
                break;
            }

            // Calculate trigonometric terms. Note: rad must be converted to f64 for math functions.
            let current_rad = rad as f64;
            let angle_radians = current_rad * std::f64::consts::PI / 180.0;

            // Accumulate coordinates (d is i32, must be cast to f64 for multiplication)
            x += d as f64 * angle_radians.cos();
            y += d as f64 * angle_radians.sin();

            // Update the angle
            rad -= r;
        }
    }

    // Cast final floating point results to integers (truncation)
    let a = x.trunc() as i32;
    let b = y.trunc() as i32;

    println!("{} {}", a, b);
    Ok(())
}