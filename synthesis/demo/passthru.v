module passthru(input a, b, output y0, y1);
  assign y0 = a & a;   // collapses to passthrough of a (.barbuf)
  assign y1 = a ^ b;
endmodule
