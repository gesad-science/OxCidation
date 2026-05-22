use std::io::{self, BufRead};

fn round_d(mut v: f64) -> f64 {
    if v >= 0.0 {
        (v + 0.5).floor()
    } else {
        -((-v) + 0.5).floor()
    }
}

fn main() {
    let stdin = stdin();
    let mut lines = stdin.lock().lines();

    // Arrays to hold the input columns
    let mut num1 = [0.0; 100];
    let mut num2 = [0.0; 100];
    let mut num3 = [0.0; 100];
    let mut num4 = [0.0; 100];
    let mut num5 = [0.0; 100];
    let mut num6 = [0.0; 100];

    // Read exactly 100 lines, each containing six numbers
    for i in 0..100 {
        let line = lines
            .next()
            .expect("Expected more input lines")
            .expect("Failed to read line");
        let mut parts = line.split_whitespace();
        num1[i] = parts
            .next()
            .expect("Missing number")
            .parse()
            .expect("Failed to parse number");
        num2[i] = parts
            .next()
            .expect("Missing number")
            .parse()
            .expect("Failed to parse number");
        num3[i] = parts
            .next()
            .expect("Missing number")
            .parse()
            .expect("Failed to parse number");
        num4[i] = parts
            .next()
            .expect("Missing number")
            .parse()
            .expect("Failed to parse number");
        num5[i] = parts
            .next()
            .expect("Missing number")
            .parse()
            .expect("Failed to parse number");
        num6[i] = parts
            .next()
            .expect("Missing number")
            .parse()
            .expect("Failed to parse number");
    }

    let mut x = 0.0;
    let mut y = 0.0;

    for i in 0..100 {
        // Replicate the complex condition from the C code
        let cond1 = !(num1[i] == 0.0 && num4[i] == 0.0);
        let cond2 = !(num2[i] == 0.0 && num5[i] != 0.0);
        let cond3 = !(num1[i] == 0.0 && num2[i] == 0.0);
        let cond4 = !(num4[i] == 0.0 && num5[i] == 0.0);
        let cond5 = (num2[i] * num4[i] - num1[i] * num5[i]) != 0.0;

        if cond1 && cond2 && cond3 && cond4 && cond5 {
            if num1[i] == 0.0 {
                y = num3[i] / num2[i];
                x = num6[i] / num4[i] - num3[i] * num5[i] / num2[i] * num4[i];
            } else if num2[i] == 0.0 {
                x = num3[i] / num1[i];
                y = num6[i] / num5[i] - num3[i] * num4[i] / num1[i] * num5[i];
            } else if num4[i] == 0.0 {
                y = num6[i] / num5[i];
                x = num3[i] / num1[i] - num2[i] * num6[i] / num1[i] * num5[i];
            } else if num5[i] == 0.0 {
                x = num6[i] / num4[i];
                y = num3[i] / num2[i] - num1[i] * num6[i] / num2[i] * num4[i];
            } else {
                let det = num2[i] * num4[i] - num1[i] * num5[i];
                x = (num2[i] * num6[i] - num3[i] * num5[i]) / det;
                x = round_d(x * 1000.0) / 1000.0;
                y = (num1[i] * num6[i] - num3[i] * num4[i]) / (num1[i] * num5[i] - num2[i] * num4[i]);
                y = round_d(y * 1000.0) / 1000.0;
            }
        }
        // Print with three digits after the decimal point
        println!("{:.3} {:.3}", x, y);
    }
}