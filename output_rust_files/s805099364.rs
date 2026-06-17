use std::io::{self, Write}; 

fn main() -> io::Result<()> {
    let mut input = String::new();
    // Read n (the number of test cases)
    io::stdin().read_line(&mut input)?;
    let n: i32 = input.trim().parse().unwrap_or(0);

    for _ in 0..n {
        input.clear();
        // Read the six coordinates (x1, y1, x2, y2, x3, y3)
        io::stdin().read_line(&mut input)?;
        let coords: Vec<f64> = input.split_whitespace()
                                  .filter_map(|s| s.parse::<f64>().ok())
                                  .collect();

        if coords.len() < 6 {
            // Handle case where input line is incomplete
            continue;
        }

        let x1 = coords[0];
        let y1 = coords[1];
        let x2 = coords[2];
        let y2 = coords[3];
        let x3 = coords[4];
        let y3 = coords[5];

        // Calculations (Direct translation of C formulas)
        let x12 = 2.0 * (x2 - x1);
        let y12 = 2.0 * (y2 - y1);
        let z12 = x1*x1 - x2*x2 + y1*y1 - y2*y2;

        let x23 = 2.0 * (x3 - x2);
        let y23 = 2.0 * (y3 - y2);
        let z23 = x2*x2 - x3*x3 + y2*y2 - y3*y3;

        // Denominator calculation
        let denominator = x12 * y23 - x23 * y12;

        // Calculate x and y (Handle potential division by zero, though the original C code assumes non-zero)
        let x: f64; 
        let y: f64;

        if denominator.abs() < 1e-9 { // Check for near zero denominator
            x = f64::NAN;
            y = f64::NAN;
        } else {
            x = (y12 * z23 - y23 * z12) / denominator;
            y = (z12 * x23 - z23 * x12) / denominator;
        }

        // Calculate r using hypot function
        let r = f64::hypot(x1 - x, y1 - y);

        // Print results formatted to three decimal places
        println!("{:.3} {:.3} {:.3}", x, y, r);
    }
    Ok(())
}