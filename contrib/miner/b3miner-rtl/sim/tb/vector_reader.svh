// ============================================================================
// vector_reader.svh -- shared TB helper for reading sim/vectors/*.hex files.
//
// Each .hex line is:
//     <label>: <hex_bytes_1> <hex_bytes_2> ...
//
// Usage:
//     `include "vector_reader.svh"
//
//     vector_record_t rec;
//     int fd;
//     fd = vr_open("blake3_compress.hex");
//     while (vr_read(fd, rec)) begin
//         // rec.label, rec.fields[i], rec.field_lens[i]
//     end
//     vr_close(fd);
// ============================================================================

`ifndef VECTOR_READER_SVH
`define VECTOR_READER_SVH

`ifndef VECT_DIR
  `define VECT_DIR "../vectors"
`endif

typedef struct {
    string         label;
    byte unsigned  fields [16][1024];
    int            field_lens [16];
    int            field_count;
} vector_record_t;

function automatic int vr_open(string filename);
    string fullpath;
    int fd;
    fullpath = {`VECT_DIR, "/", filename};
    fd = $fopen(fullpath, "r");
    if (fd == 0) begin
        $error("vector_reader: failed to open %s", fullpath);
    end
    return fd;
endfunction

function automatic void vr_close(int fd);
    if (fd != 0) $fclose(fd);
endfunction

// Parse one record line.  Returns 1 if a record was read, 0 on EOF.
function automatic int vr_read(int fd, ref vector_record_t rec);
    string line;
    string token;
    int    pos;
    int    line_len;
    int    char;
    int    nibble;
    int    bytes_in_field;

    rec.label       = "";
    rec.field_count = 0;
    for (int i = 0; i < 16; i++) rec.field_lens[i] = 0;

    while (!$feof(fd)) begin
        line = "";
        // read up to newline
        char = $fgetc(fd);
        while (char != -1 && char != "\n") begin
            line = {line, string'(byte'(char))};
            char = $fgetc(fd);
        end
        // skip blanks + comments
        if (line.len() == 0)            continue;
        if (line.substr(0, 0) == "#")    continue;
        if (line.substr(0, 0) == "\r")   continue;
        // split on ":"
        pos = -1;
        for (int i = 0; i < line.len(); i++) begin
            if (line[i] == ":") begin pos = i; break; end
        end
        if (pos < 0) continue;
        rec.label = line.substr(0, pos - 1);
        line = line.substr(pos + 1, line.len() - 1);

        // Tokenize by whitespace; each token is one hex field.
        rec.field_count = 0;
        token           = "";
        bytes_in_field  = 0;
        for (int i = 0; i <= line.len(); i++) begin
            char = (i == line.len()) ? " " : line[i];
            if (char == " " || char == "\t" || char == "\r") begin
                if (token.len() > 0) begin
                    if (rec.field_count >= 16) begin
                        $error("vector_reader: too many fields on line: %s", rec.label);
                        return 0;
                    end
                    if ((token.len() % 2) != 0) begin
                        $error("vector_reader: odd hex digit count for %s", rec.label);
                        return 0;
                    end
                    bytes_in_field = token.len() / 2;
                    for (int b = 0; b < bytes_in_field; b++) begin
                        byte unsigned hi, lo;
                        hi = vr_nibble(token[2*b]);
                        lo = vr_nibble(token[2*b + 1]);
                        rec.fields[rec.field_count][b] = (hi << 4) | lo;
                    end
                    rec.field_lens[rec.field_count] = bytes_in_field;
                    rec.field_count++;
                    token = "";
                end
            end else begin
                token = {token, string'(byte'(char))};
            end
        end
        return 1;
    end
    return 0;
endfunction

function automatic byte unsigned vr_nibble(byte unsigned c);
    if (c >= "0" && c <= "9") return c - "0";
    if (c >= "a" && c <= "f") return 10 + (c - "a");
    if (c >= "A" && c <= "F") return 10 + (c - "A");
    return 0;
endfunction

`endif  // VECTOR_READER_SVH
